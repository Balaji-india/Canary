"""Record what an experiment script hands to scikit-learn, without changing what it computes (Mission 5.1).

Why: the tripwires check a chain of custody (docs/plans/mission_5_1_tripwires.md, section 1): the registered split,
fits on training rows only, one model per arm predicting the test rows, the registered metric on exactly those rows.
Reading the script's text cannot prove that (padding, shams and decoys change the text but not the numbers), so the
script is run once more and this probe writes down what reaches a few scikit-learn entry points. The checks then
work on that record, the *trace*, as pure functions.

How it is started: `canary/replay.py` copies this file next to a copy of the run's script and runs
`python -I probe.py [experiment.py [trace.json]]` there. The probe executes the script's own import lines, wraps the
entry points, then runs the script as `__main__`. Standalone on purpose: it imports the standard library, numpy,
pandas and scikit-learn, never `canary`, so a replay depends on nothing the run folder does not hold.

What is wrapped (the list comes from the library, not from the template):
- `sklearn.model_selection.train_test_split`;
- on every loaded scikit-learn estimator class (and the mixins it inherits): `fit`, `fit_transform`, `fit_predict`,
  `transform`, `predict`, `predict_proba`, `decision_function`, `score`;
- every public function in `sklearn.metrics` whose first parameter is `y_true`.

Only script-level calls are recorded: the caller's code must be the script file, and no recorded call may already be
running. So fits inside a pipeline, a grid search's internal folds and scikit-learn's own metric calls are skipped.

Transparency: a wrapper must not change what the script sees. `predict_proba` on `SVC`, `Pipeline` and
`GridSearchCV` is a *conditional* attribute (a descriptor that raises AttributeError when the method is not
available); replacing it with a plain function would make `hasattr(model, "predict_proba")` true and send the template
down another branch. Such descriptors are wrapped by a descriptor that asks the original first, so `hasattr` answers
as it does without the probe. The replay test compares every number with a plain run.

Rows are identified by content (`row_fingerprints`): a 64-bit hash of one row's values, numbers as float64 and
anything else as text, the index ignored. No variable name, function name or line of the script is recorded.

Limits: the script runs in the probe's process, so a script could undo the wrappers (same threat model as the sandbox:
accidents and planted bugs, not attacks). Estimator classes first imported while the script runs are not wrapped;
their calls are simply missing from the trace, which the checks treat as "unverifiable".
"""
from __future__ import annotations

import ast
import functools
import hashlib
import inspect
import json
import os
import runpy
import sys
import threading
import time
import traceback

import numpy as np
import pandas as pd

TRACE_VERSION = 1
DEFAULT_SCRIPT = "experiment.py"
DEFAULT_TRACE = "trace.json"
ESTIMATOR_METHODS = ("fit", "fit_transform", "fit_predict", "transform", "predict", "predict_proba",
                     "decision_function", "score")
# Outputs of these methods are kept as values, so a metric's arguments can later be linked to the call that made them.
VALUE_OUTPUTS = ("predict", "fit_predict", "predict_proba", "decision_function")
ERROR_TAIL_CHARS = 2000
_PARAM_DEPTH = 6
_WRAPPED = "_probe_original"  # attribute set on every wrapper, so nothing is wrapped twice

# ---- Row fingerprints -------------------------------------------------------------------------------------------

# Every NaN (np.nan, float("nan"), None, pd.NA) gets one fixed bit pattern, so a missing value always hashes the same.
_NAN_WORD = np.uint64(0x7FF8000000000001)


def _number_words(values) -> np.ndarray:
    """One 64-bit word per number: its float64 bits, with -0.0 read as 0.0 and every NaN as one pattern."""
    numbers = np.asarray(values, dtype=np.float64) + 0.0  # adding 0.0 turns -0.0 into 0.0
    words = numbers.view(np.uint64).copy()
    words[np.isnan(numbers)] = _NAN_WORD
    return words


def _text_word(value) -> int:
    digest = hashlib.blake2b(str(value).encode("utf-8", "surrogatepass"), digest_size=8, person=b"text")
    return int.from_bytes(digest.digest(), "little")


def _is_missing(value) -> bool:
    return value is None or value is pd.NA or (isinstance(value, float) and value != value)


def _object_words(values) -> np.ndarray:
    """Words for values of mixed type: numbers as numbers (so 1, 1.0 and True agree), anything else as text."""
    words = np.empty(len(values), dtype=np.uint64)
    for i, value in enumerate(values):
        if _is_missing(value):
            words[i] = _NAN_WORD
        elif isinstance(value, (int, float, np.integer, np.floating, np.bool_)):
            words[i] = _number_words([value])[0]
        else:
            words[i] = _text_word(value)
    return words


def _column_words(column) -> np.ndarray:
    if isinstance(column, pd.Series):
        if pd.api.types.is_numeric_dtype(column.dtype) and not pd.api.types.is_complex_dtype(column.dtype):
            return _number_words(column.to_numpy(dtype=np.float64, na_value=np.nan))
        return _object_words(column.to_numpy(dtype=object))
    array = np.asarray(column)
    if array.dtype.kind in "biuf":
        return _number_words(array)
    return _object_words(array.astype(object))


def _word_matrix(data) -> np.ndarray:
    """An (n rows, n columns) array of words. Data frames: columns in name order, index ignored."""
    if isinstance(data, pd.DataFrame):
        order = sorted(range(data.shape[1]), key=lambda i: str(data.columns[i]))
        columns = [_column_words(data.iloc[:, i]) for i in order]
        n_rows = len(data)
    elif isinstance(data, pd.Series):
        columns, n_rows = [_column_words(data)], len(data)
    else:
        if hasattr(data, "toarray"):  # a scipy sparse matrix
            data = data.toarray()
        array = np.asarray(data)
        if array.ndim == 0:
            array = array.reshape(1)
        if array.ndim == 1:
            columns, n_rows = [_column_words(array)], len(array)
        else:
            array = array.reshape(len(array), -1)
            columns, n_rows = [_column_words(array[:, j]) for j in range(array.shape[1])], len(array)
    if not columns:
        return np.zeros((n_rows, 0), dtype="<u8")
    return np.ascontiguousarray(np.column_stack(columns).astype("<u8"))


def row_fingerprints(data) -> list[int]:
    """Return one 64-bit fingerprint per row of `data` (a data frame, series, array or list).

    Numbers count as float64, so an int column and its float copy agree; anything else counts as its text. The index
    is ignored and a data frame's columns are taken in name order, so re-indexing or re-ordering columns changes
    nothing. Identical rows get identical fingerprints: the checks count them as multisets, never as sets.
    """
    matrix = _word_matrix(data)
    return [int.from_bytes(hashlib.blake2b(row.tobytes(), digest_size=8).digest(), "little") for row in matrix]


# ---- Describing arguments and results --------------------------------------------------------------------------

def _values(data) -> list:
    if hasattr(data, "toarray"):
        data = data.toarray()
    return data.tolist() if isinstance(data, pd.Series) else np.asarray(data).tolist()


def describe(data, values: bool = False) -> dict | None:
    """What the trace keeps about one data argument: type, shape, column names, row fingerprints, and the values
    themselves for one-dimensional data (labels, predictions) or when `values` is set. Never raises."""
    if data is None:
        return None
    info: dict = {"type": type(data).__name__}
    try:
        if isinstance(data, pd.DataFrame):
            info["columns"] = [str(c) for c in data.columns]
        shape = list(getattr(data, "shape", np.shape(data)))
        info["shape"] = [int(s) for s in shape]
        info["fp"] = row_fingerprints(data)
        if values or len(shape) == 1:
            info["values"] = _values(data)
    except Exception as exc:  # a description must never break the script it describes
        info["error"] = repr(exc)
    return info


def _is_data(value) -> bool:
    return isinstance(value, (np.ndarray, pd.Series, pd.DataFrame)) or hasattr(value, "toarray")


def plain(value, depth: int = 0):
    """A JSON-friendly copy of a parameter or keyword value. Estimators become their class and parameters."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if depth >= _PARAM_DEPTH:
        return {"repr": repr(value)[:200]}
    if _is_data(value):
        return {"data": describe(value)}
    if isinstance(value, (list, tuple)):
        return [plain(v, depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v, depth + 1) for k, v in value.items()}
    if hasattr(value, "get_params") and not isinstance(value, type):
        return {"estimator": _class_name(value), "params": _params_of(value, depth + 1)}
    return {"repr": repr(value)[:200]}


def _class_name(obj) -> str:
    return f"{type(obj).__module__}.{type(obj).__qualname__}"


def _params_of(obj, depth: int = 0):
    try:
        return plain(obj.get_params(deep=False), depth)
    except Exception as exc:
        return {"error": repr(exc)}


def _describe_output(method: str, obj, result):
    if method == "fit":
        return {"returns_self": result is obj}
    if method == "score":
        return plain(result)
    return describe(result, values=method in VALUE_OUTPUTS)


# ---- The recorder ------------------------------------------------------------------------------------------------

class Recorder:
    """Collects script-level calls. One instance per probed script."""

    def __init__(self, script_path: str):
        self.script = os.path.normcase(os.path.abspath(script_path))
        self.events: list[dict] = []
        self._local = threading.local()
        self._is_script_file: dict[str, bool] = {}
        self._ids: dict[int, int] = {}
        self._keep: list = []  # holds every numbered object, so a Python id is never reused for another one

    def at_script_level(self, frame) -> bool:
        """True when the caller's code is the script and no recorded call is already running."""
        if getattr(self._local, "depth", 0):
            return False
        name = frame.f_code.co_filename
        hit = self._is_script_file.get(name)
        if hit is None:
            hit = self._is_script_file[name] = os.path.normcase(os.path.abspath(name)) == self.script
        return hit

    def object_id(self, obj) -> int:
        key = id(obj)
        if key not in self._ids:
            self._ids[key] = len(self._ids)
            self._keep.append(obj)
        return self._ids[key]

    def run(self, event: dict, call, args, kwargs, describe_result):
        """Make the real call with recording switched off inside it, then store the event."""
        self._local.depth = 1
        try:
            result = call(*args, **kwargs)
        except BaseException as exc:
            event["raised"] = type(exc).__name__
            self._store(event)
            raise
        finally:
            self._local.depth = 0
        try:
            event["out"] = describe_result(result)
        except Exception as exc:
            event["out"] = {"error": repr(exc)}
        self._store(event)
        return result

    def _store(self, event: dict) -> None:
        event["seq"] = len(self.events)
        self.events.append(event)

    def estimator_call(self, method: str, obj, call, args, kwargs):
        X = args[0] if args else kwargs.get("X")
        y = args[1] if len(args) > 1 else kwargs.get("y")
        event = {
            "kind": "estimator", "method": method, "obj": self.object_id(obj), "cls": _class_name(obj),
            "params": _params_of(obj), "X": describe(X), "y": describe(y),
            "other_args": len(args) > 2 or sorted(k for k in kwargs if k not in ("X", "y")),
        }
        return self.run(event, call, args, kwargs, lambda result: _describe_output(method, obj, result))

    def metric_call(self, name: str, func, parameters: list[str], args, kwargs):
        try:
            bound = inspect.signature(func).bind_partial(*args, **kwargs).arguments
        except TypeError:  # the real call will raise the same error
            bound = {}
        second = parameters[1] if len(parameters) > 1 else None
        event = {
            "kind": "metric", "func": name, "y_true": describe(bound.get("y_true")),
            "second_name": second, "second": describe(bound.get(second), values=True) if second else None,
            "kwargs": {k: plain(v) for k, v in bound.items() if k not in ("y_true", second)},
        }
        return self.run(event, func, args, kwargs, plain)

    def split_call(self, func, args, kwargs):
        event = {
            "kind": "split", "func": "train_test_split", "inputs": [describe(a) for a in args],
            "kwargs": {k: plain(v) for k, v in kwargs.items()},
        }
        return self.run(event, func, args, kwargs, lambda result: [describe(part) for part in result])


# ---- Wrappers ----------------------------------------------------------------------------------------------------

def _wrap_method(recorder: Recorder, name: str, func):
    """Wrap a plain method. A plain function is always available, so wrapping it cannot change `hasattr`."""
    @functools.wraps(func)
    def watched(self, *args, **kwargs):
        if not recorder.at_script_level(sys._getframe(1)):
            return func(self, *args, **kwargs)
        return recorder.estimator_call(name, self, functools.partial(func, self), args, kwargs)

    setattr(watched, _WRAPPED, func)
    return watched


class _WatchedDescriptor:
    """Wrap a conditional method (scikit-learn's `available_if`). The original descriptor is asked first, so when it
    raises AttributeError (the method is not available on this object) the wrapper raises it too."""

    def __init__(self, recorder: Recorder, name: str, inner):
        self.recorder, self.name, self.inner = recorder, name, inner
        setattr(self, _WRAPPED, inner)

    def __get__(self, obj, owner=None):
        bound = self.inner.__get__(obj, owner)
        if obj is None:
            return bound
        recorder, name = self.recorder, self.name

        @functools.wraps(bound)
        def watched(*args, **kwargs):
            if not recorder.at_script_level(sys._getframe(1)):
                return bound(*args, **kwargs)
            return recorder.estimator_call(name, obj, bound, args, kwargs)

        return watched


def _estimator_classes():
    """Every scikit-learn estimator class in a loaded module, with the scikit-learn classes it inherits from."""
    from sklearn.base import BaseEstimator

    found, seen = [], set()
    for module_name, module in list(sys.modules.items()):
        if not (module_name == "sklearn" or module_name.startswith("sklearn.")) or module is None:
            continue
        for value in list(vars(module).values()):
            try:
                is_estimator = isinstance(value, type) and issubclass(value, BaseEstimator)
            except TypeError:
                continue
            if not is_estimator:
                continue
            for klass in value.__mro__:
                if klass not in seen and klass.__module__.startswith("sklearn"):
                    seen.add(klass)
                    found.append(klass)
    return found


def _install_estimators(recorder: Recorder) -> int:
    wrapped = 0
    for klass in _estimator_classes():
        for name in ESTIMATOR_METHODS:
            attr = klass.__dict__.get(name)
            if attr is None or hasattr(attr, _WRAPPED):
                continue
            if inspect.isfunction(attr):
                setattr(klass, name, _wrap_method(recorder, name, attr))
            elif hasattr(attr, "__get__") and not isinstance(attr, (staticmethod, classmethod, property)):
                setattr(klass, name, _WatchedDescriptor(recorder, name, attr))
            else:
                continue
            wrapped += 1
    return wrapped


def _install_metrics(recorder: Recorder) -> int:
    import sklearn.metrics as metrics

    wrapped = 0
    for name in getattr(metrics, "__all__", dir(metrics)):
        func = getattr(metrics, name, None)
        if not callable(func) or isinstance(func, type) or hasattr(func, _WRAPPED):
            continue
        try:
            parameters = list(inspect.signature(func).parameters)
        except (TypeError, ValueError):
            continue
        if not parameters or parameters[0] != "y_true":
            continue

        def watched(*args, _func=func, _name=name, _parameters=parameters, **kwargs):
            if not recorder.at_script_level(sys._getframe(1)):
                return _func(*args, **kwargs)
            return recorder.metric_call(_name, _func, _parameters, args, kwargs)

        functools.update_wrapper(watched, func)
        setattr(watched, _WRAPPED, func)
        setattr(metrics, name, watched)
        wrapped += 1
    return wrapped


def _install_split(recorder: Recorder) -> None:
    import sklearn.model_selection as model_selection

    original = model_selection.train_test_split
    if hasattr(original, _WRAPPED):
        return

    @functools.wraps(original)
    def watched(*args, **kwargs):
        if not recorder.at_script_level(sys._getframe(1)):
            return original(*args, **kwargs)
        return recorder.split_call(original, args, kwargs)

    setattr(watched, _WRAPPED, original)
    model_selection.train_test_split = watched


def install(recorder: Recorder) -> dict:
    """Wrap the entry points for this process. Returns how many of each were wrapped."""
    _install_split(recorder)
    return {"estimator_methods": _install_estimators(recorder), "metrics": _install_metrics(recorder)}


def _run_import_lines(script_path: str) -> None:
    """Execute the script's own top-level import lines, so its estimator classes are loaded before wrapping.

    A failing import is ignored here: the script itself will fail on it in the same way when it runs.
    """
    with open(script_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=script_path)
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    for node in imports:
        try:
            exec(compile(ast.Module(body=[node], type_ignores=[]), script_path, "exec"), {"__name__": "_probe_imports"})
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    """Run a script under the probe and write its trace, even when the script fails. Returns the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    script_path = os.path.abspath(argv[0] if argv else DEFAULT_SCRIPT)
    trace_path = os.path.abspath(argv[1] if len(argv) > 1 else DEFAULT_TRACE)
    recorder = Recorder(script_path)
    trace = {"version": TRACE_VERSION, "script": os.path.basename(script_path), "status": "started",
             "error": None, "wrapped": None, "events": recorder.events, "seconds": None}
    started = time.perf_counter()
    code = 0
    try:
        _run_import_lines(script_path)
        trace["wrapped"] = install(recorder)
        sys.argv = [script_path]
        runpy.run_path(script_path, run_name="__main__")
        trace["status"] = "finished"
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        trace["status"] = "finished" if code == 0 else "exited"
    except BaseException:
        trace["status"] = "raised"
        trace["error"] = traceback.format_exc()[-ERROR_TAIL_CHARS:]
        traceback.print_exc()
        code = 1
    finally:
        trace["seconds"] = time.perf_counter() - started
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace, f)
    return code


if __name__ == "__main__":
    sys.exit(main())
