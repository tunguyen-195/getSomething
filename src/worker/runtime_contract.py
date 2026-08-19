"""Deterministic request-contract fingerprints for live Celery workers."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import cached_property, partial
from pathlib import Path
from typing import Any, get_args, get_origin


WORKER_RUNTIME_CONTRACT_VERSION = "worker-runtime-contract-v2"
SUMMARY_IMPLEMENTATION_CONTRACT_VERSION = "summary-implementation-contract-v1"
WORKER_RUNTIME_CONTRACT_TASK = "tasks.worker_runtime_contract"
SUMMARY_TASK_NAME = "tasks.summarize_transcript"
_SUMMARY_IMPLEMENTATION_MODULES = (
    "src.core.config",
    "src.worker.tasks.summarize_task",
    "src.services.task_service",
    "src.services.model_runtime.gpu_lease",
    "src.services.investigation.claim_semantics",
    "src.services.investigation.contracts",
    "src.services.investigation.evidence_selector",
    "src.services.investigation.exact_detectors",
    "src.services.investigation.narrative_attestation",
    "src.services.investigation.run_contracts",
    "src.services.investigation.source_revision",
    "src.services.investigation.verification_contracts",
    "src.services.summarization.contracts",
    "src.services.summarization.summary_service_v2",
    "src.services.summarization.context_service",
    "src.services.summarization.deterministic_analysis",
    "src.services.summarization.investigation_preview",
    "src.services.summarization.legacy_context_adapter",
    "src.services.summarization.bulletin_writer",
    "src.services.summarization.models.context_analysis",
    "src.services.summarization.models.investigation_knowledge",
    "src.services.summarization.models.llm_manager",
    "src.services.summarization.models.openai_compatible_client",
    "src.services.summarization.investigation_scenarios",
    "src.services.summarization.public_projection",
)
_SUMMARY_RUNTIME_SETTING_NAMES = (
    "OFFLINE_STRICT",
    "ENABLE_HIGH_RISK_AI_FIELDS",
    "STORE_RAW_LLM_RESPONSES",
    "GPU_LEASE_ENABLED",
    "GPU_LEASE_PATH",
    "GPU_LEASE_TIMEOUT_SECONDS",
    "UNLOAD_MODELS_AFTER_TASK",
    "LOCAL_LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_NUM_CTX",
    "LLAMA_SERVER_BASE_URL",
    "LLAMA_SERVER_MODEL",
    "LLAMA_SERVER_MODEL_PATH",
    "LLAMA_SERVER_CONTEXT_SIZE",
    "LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB",
    "LLAMA_SERVER_SLEEP_IDLE_SECONDS",
    "LLAMA_SERVER_SLEEP_WAIT_SECONDS",
    "LLM_SEED",
    "LLM_CONNECT_TIMEOUT_SECONDS",
    "LLM_READ_TIMEOUT_SECONDS",
    "LLM_HEALTH_CACHE_SECONDS",
    "SUMMARY_SINGLE_PASS_INVESTIGATION",
    "FORCE_VIETNAMESE_OUTPUT",
    "TRANSLATE_SUMMARY_TO_VIETNAMESE",
)
_MUTABLE_CLOSURE_STATE_ALLOWLIST = {
    (
        "src.services.investigation.run_contracts",
        "_build_release_authority_bridge.<locals>.consume",
    ): frozenset({"minted", "released"}),
    (
        "src.services.investigation.run_contracts",
        "_build_release_authority_bridge.<locals>.verify_released",
    ): frozenset({"released"}),
}
_MUTABLE_CLASS_STATE_ALLOWLIST = {
    (
        "src.services.summarization.models.llm_manager",
        "LLMManager",
    ): frozenset({"_instance", "_initialized"}),
}


class RuntimeContractUnsupportedState(RuntimeError):
    """Raised when mutable closure state cannot be fingerprinted safely."""


def _json_default(value: object) -> object:
    if value is inspect.Parameter.empty:
        return {"kind": "required"}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_default(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_default(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    value_type = type(value)
    return {
        "kind": "python",
        "type": f"{value_type.__module__}.{value_type.__qualname__}",
    }


def task_request_schema(task_callable: Callable[..., object]) -> dict[str, Any]:
    """Describe only the wire-relevant callable surface in canonical order."""

    signature = inspect.signature(task_callable)
    parameters: list[dict[str, Any]] = []
    for parameter in signature.parameters.values():
        if parameter.name == "self":
            continue
        row: dict[str, Any] = {
            "name": parameter.name,
            "kind": parameter.kind.name,
            "required": parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD},
        }
        if parameter.default is not inspect.Parameter.empty:
            row["default"] = _json_default(parameter.default)
        parameters.append(row)
    return {"parameters": parameters}


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_runtime_value(
    value: object,
    *,
    _seen: set[int] | None = None,
    include_object_state: bool = False,
) -> object:
    """Serialize stable runtime semantics without reading source from disk."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "sha256": hashlib.sha256(value).hexdigest(),
            "length": len(value),
        }
    if isinstance(value, Path):
        return {"kind": "path", "value": str(value)}
    if isinstance(value, Enum):
        value_type = type(value)
        return {
            "kind": "enum",
            "type": f"{value_type.__module__}.{value_type.__qualname__}",
            "value": _canonical_runtime_value(
                value.value,
                _seen=_seen,
                include_object_state=include_object_state,
            ),
        }
    origin = get_origin(value)
    if origin is not None:
        return {
            "kind": "typing",
            "origin": _canonical_runtime_value(
                origin,
                _seen=_seen,
                include_object_state=include_object_state,
            ),
            "args": [
                _canonical_runtime_value(
                    item,
                    _seen=_seen,
                    include_object_state=include_object_state,
                )
                for item in get_args(value)
            ],
        }
    forward_arg = getattr(value, "__forward_arg__", None)
    if isinstance(forward_arg, str):
        return {"kind": "forward_ref", "value": forward_arg}
    if isinstance(value, type):
        return {
            "kind": "type_ref",
            "type": f"{value.__module__}.{value.__qualname__}",
        }
    if isinstance(value, re.Pattern):
        return {
            "kind": "regex",
            "pattern": value.pattern,
            "flags": value.flags,
        }
    seen = _seen if _seen is not None else set()
    value_id = id(value)
    if value_id in seen:
        value_type = type(value)
        return {
            "kind": "cycle",
            "type": f"{value_type.__module__}.{value_type.__qualname__}",
        }
    seen.add(value_id)
    try:
        return _canonical_runtime_composite(
            value,
            seen,
            include_object_state=include_object_state,
        )
    finally:
        seen.remove(value_id)


def _canonical_runtime_composite(
    value: object,
    seen: set[int],
    *,
    include_object_state: bool,
) -> object:
    if include_object_state and isinstance(value, (dict, list, set)):
        raise RuntimeContractUnsupportedState(
            "mutable closure containers require an immutable contract value"
        )
    if isinstance(value, Mapping):
        return {
            "kind": "mapping",
            "items": {
                str(key): _canonical_runtime_value(
                    item,
                    _seen=seen,
                    include_object_state=include_object_state,
                )
                for key, item in sorted(
                    value.items(),
                    key=lambda pair: str(pair[0]),
                )
            },
        }
    if isinstance(value, (list, tuple)):
        return {
            "kind": "list" if isinstance(value, list) else "tuple",
            "items": [
                _canonical_runtime_value(
                    item,
                    _seen=seen,
                    include_object_state=include_object_state,
                )
                for item in value
            ],
        }
    if isinstance(value, (set, frozenset)):
        items = [
            _canonical_runtime_value(
                item,
                _seen=seen,
                include_object_state=include_object_state,
            )
            for item in value
        ]
        return {
            "kind": "set" if isinstance(value, set) else "frozenset",
            "items": sorted(
                items,
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        }
    if is_dataclass(value) and not isinstance(value, type):
        dataclass_params = getattr(type(value), "__dataclass_params__", None)
        if not bool(getattr(dataclass_params, "frozen", False)):
            return {
                "kind": "mutable_dataclass",
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
                "class": _class_implementation_payload(type(value)),
                "fields": {
                    field.name: _mutable_state_member_payload(
                        getattr(value, field.name)
                    )
                    for field in fields(value)
                },
            }
        return {
            "kind": "dataclass",
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                field.name: _canonical_runtime_value(
                    getattr(value, field.name),
                    _seen=seen,
                    include_object_state=include_object_state,
                )
                for field in fields(value)
            },
        }
    value_type = type(value)
    if not include_object_state:
        return {
            "kind": "python",
            "type": f"{value_type.__module__}.{value_type.__qualname__}",
        }
    state: dict[str, Any] = {}
    try:
        attributes = vars(value)
    except TypeError:
        attributes = {}
    for name, item in sorted(attributes.items()):
        if inspect.ismodule(item):
            continue
        state[name] = _mutable_state_member_payload(item)
    slots = getattr(value_type, "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    for name in slots:
        if not isinstance(name, str) or name in state or not hasattr(value, name):
            continue
        item = getattr(value, name)
        if inspect.ismodule(item):
            continue
        state[name] = _mutable_state_member_payload(item)
    return {
        "kind": "python_object",
        "type": f"{value_type.__module__}.{value_type.__qualname__}",
        "class": _class_implementation_payload(value_type),
        "state_schema": state,
    }


def _mutable_state_member_payload(value: object) -> object:
    if callable(value):
        return _callable_implementation_payload(value)
    value_type = type(value)
    raise RuntimeContractUnsupportedState(
        "mutable closure object contains non-callable state of type "
        f"{value_type.__module__}.{value_type.__qualname__}"
    )


def _code_constant_payload(value: object) -> object:
    if isinstance(value, types.CodeType):
        return {"kind": "code", "payload": _code_implementation_payload(value)}
    return _canonical_runtime_value(value)


def _code_implementation_payload(code: types.CodeType) -> dict[str, Any]:
    """Describe executable semantics without source paths or line-number tables."""

    return {
        "bytecode_sha256": hashlib.sha256(code.co_code).hexdigest(),
        "exception_table_sha256": hashlib.sha256(code.co_exceptiontable).hexdigest(),
        "constants": [_code_constant_payload(item) for item in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
    }


def _callable_layer_payload(value: Callable[..., object]) -> dict[str, Any]:
    target = value.__func__ if inspect.ismethod(value) else value
    code = getattr(target, "__code__", None)
    if not isinstance(code, types.CodeType):
        if isinstance(target, partial):
            return {
                "kind": "partial",
                "callable": _callable_implementation_payload(target.func),
                "args": [
                    _bound_callable_value_payload(item) for item in target.args
                ],
                "keywords": {
                    str(key): _bound_callable_value_payload(item)
                    for key, item in sorted((target.keywords or {}).items())
                },
            }
        if callable(target) and not inspect.isroutine(target):
            return {
                "kind": "callable_object",
                "object": _canonical_runtime_value(
                    target,
                    include_object_state=True,
                ),
            }
        return {
            "kind": "callable",
            "type": f"{type(target).__module__}.{type(target).__qualname__}",
        }
    closure = []
    generated_callable = _is_generated_callable(target, code)
    allowed_mutable_cells = _MUTABLE_CLOSURE_STATE_ALLOWLIST.get(
        (
            str(getattr(target, "__module__", "")),
            str(getattr(target, "__qualname__", "")),
        ),
        frozenset(),
    )
    for freevar_name, cell in zip(
        code.co_freevars,
        getattr(target, "__closure__", None) or (),
    ):
        try:
            closure.append(
                _closure_value_payload(
                    cell.cell_contents,
                    allow_generated_mutable_state=generated_callable,
                    allow_runtime_mutable_state=(
                        freevar_name in allowed_mutable_cells
                    ),
                )
            )
        except ValueError:
            closure.append({"kind": "empty_cell"})
    defaults = getattr(target, "__defaults__", None)
    kwdefaults = getattr(target, "__kwdefaults__", None)
    return {
        "kind": "python_code",
        "code": _code_implementation_payload(code),
        "defaults": (
            [_closure_value_payload(item) for item in defaults]
            if defaults is not None
            else None
        ),
        "kwdefaults": (
            {
                key: _closure_value_payload(item)
                for key, item in sorted(kwdefaults.items())
            }
            if kwdefaults is not None
            else None
        ),
        "annotations": _canonical_runtime_value(
            getattr(target, "__annotations__", None)
        ),
        "closure": closure,
    }


def _bound_callable_value_payload(value: object) -> object:
    if callable(value):
        return _callable_implementation_payload(value)
    if isinstance(value, (dict, list, set)):
        raise RuntimeContractUnsupportedState(
            "partial arguments cannot contain mutable containers"
        )
    return _canonical_runtime_value(value, include_object_state=True)


def _closure_value_payload(
    value: object,
    *,
    allow_generated_mutable_state: bool = False,
    allow_runtime_mutable_state: bool = False,
) -> object:
    if callable(value):
        return _callable_implementation_payload(value)
    if allow_runtime_mutable_state:
        value_type = type(value)
        return {
            "kind": "allowlisted_runtime_state",
            "type": f"{value_type.__module__}.{value_type.__qualname__}",
        }
    if allow_generated_mutable_state and isinstance(value, (dict, list, set)):
        value_type = type(value)
        return {
            "kind": "generated_mutable_state",
            "type": f"{value_type.__module__}.{value_type.__qualname__}",
        }
    return _canonical_runtime_value(value, include_object_state=True)


def _is_generated_callable(
    target: Callable[..., object],
    code: types.CodeType,
) -> bool:
    module = sys.modules.get(str(getattr(target, "__module__", "")))
    module_origin = getattr(module, "__file__", None) if module is not None else None
    if not module_origin:
        return False
    try:
        return Path(code.co_filename).resolve() != Path(module_origin).resolve()
    except (OSError, RuntimeError):
        return str(code.co_filename).casefold() != str(module_origin).casefold()


def _callable_implementation_payload(value: Callable[..., object]) -> dict[str, Any]:
    layers: list[dict[str, Any]] = []
    current: object = value
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        layers.append(_callable_layer_payload(current))
        target = current.__func__ if inspect.ismethod(current) else current
        wrapped = getattr(target, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
    return {"kind": "callable_chain", "layers": layers}


def _class_implementation_payload(value: type[object]) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    descriptors: dict[str, Any] = {}
    constants: dict[str, Any] = {}
    ignored_runtime_state = _MUTABLE_CLASS_STATE_ALLOWLIST.get(
        (str(value.__module__), str(value.__qualname__)),
        frozenset(),
    )
    for name, member in vars(value).items():
        if name in ignored_runtime_state:
            continue
        target = (
            member.__func__
            if isinstance(member, (classmethod, staticmethod))
            else member
        )
        if inspect.isfunction(target):
            methods[name] = _callable_implementation_payload(target)
        elif isinstance(member, property):
            descriptors[name] = {
                "kind": "property",
                "get": _optional_callable_payload(member.fget),
                "set": _optional_callable_payload(member.fset),
                "delete": _optional_callable_payload(member.fdel),
            }
        elif isinstance(member, cached_property):
            descriptors[name] = {
                "kind": "cached_property",
                "implementation": _callable_implementation_payload(member.func),
            }
        elif (
            not name.startswith("__")
            and name != "model_fields"
            and _is_semantic_runtime_value(member)
        ):
            constants[name] = _canonical_runtime_value(member)

    payload: dict[str, Any] = {
        "methods": methods,
        "descriptors": descriptors,
        "constants": constants,
        "annotations": _canonical_runtime_value(
            getattr(value, "__annotations__", {})
        ),
    }
    model_json_schema = getattr(value, "model_json_schema", None)
    if callable(model_json_schema):
        payload["model_json_schema"] = model_json_schema()
    return payload


def _optional_callable_payload(value: object) -> object:
    if not callable(value):
        return None
    return _callable_implementation_payload(value)


def _is_semantic_runtime_value(value: object) -> bool:
    return (
        value is None
        or isinstance(
            value,
            (
                bool,
                int,
                float,
                str,
                bytes,
                Path,
                Enum,
                re.Pattern,
                Mapping,
                list,
                tuple,
                set,
                frozenset,
            ),
        )
        or (is_dataclass(value) and not isinstance(value, type))
        or get_origin(value) is not None
        or isinstance(getattr(value, "__forward_arg__", None), str)
    )


def _module_origin_payload(module: types.ModuleType) -> dict[str, Any] | None:
    """Describe import layout without binding the digest to an absolute drive."""

    origin = getattr(module, "__file__", None)
    if not origin:
        return None
    origin_path = Path(origin)
    logical_path = module.__name__.replace(".", "/")
    if origin_path.stem == "__init__":
        logical_path = f"{logical_path}/__init__.py"
    else:
        logical_path = f"{logical_path}.py"
    normalized_origin = str(origin_path).replace("\\", "/")
    return {
        "kind": "python_file",
        "logical_path": logical_path,
        "logical_path_matches": normalized_origin.casefold().endswith(
            logical_path.casefold()
        ),
    }


def _module_implementation_digest(module_name: str) -> str:
    module = importlib.import_module(module_name)
    functions: dict[str, Any] = {}
    classes: dict[str, Any] = {}
    repo_dependencies: dict[str, Any] = {}
    constants: dict[str, Any] = {}
    for name, value in vars(module).items():
        if inspect.isfunction(value) and value.__module__ == module.__name__:
            functions[name] = _callable_implementation_payload(value)
        elif inspect.isclass(value) and value.__module__ == module.__name__:
            classes[name] = _class_implementation_payload(value)
        elif inspect.isfunction(value) and str(value.__module__).startswith("src."):
            repo_dependencies[name] = {
                "module": value.__module__,
                "implementation": _callable_implementation_payload(value),
            }
        elif inspect.isclass(value) and str(value.__module__).startswith("src."):
            repo_dependencies[name] = {
                "module": value.__module__,
                "implementation": _class_implementation_payload(value),
            }
        elif not name.startswith("__") and _is_semantic_runtime_value(value):
            constants[name] = _canonical_runtime_value(value)

    payload = {
        "module": module.__name__,
        "origin": _module_origin_payload(module),
        "functions": functions,
        "classes": classes,
        "repo_dependencies": repo_dependencies,
        "constants": constants,
    }
    return _fingerprint(payload)


def _summary_runtime_settings_digest() -> str:
    config = importlib.import_module("src.core.config")
    settings = getattr(config, "settings")
    payload = {
        name: _canonical_runtime_value(getattr(settings, name, None))
        for name in _SUMMARY_RUNTIME_SETTING_NAMES
    }
    return _fingerprint(payload)


def summary_implementation_contract(
    summary_task_callable: Callable[..., object],
) -> dict[str, Any]:
    """Fingerprint code already loaded by the worker, including writer safety."""

    components = {
        "summary_task_callable": _fingerprint(
            _callable_implementation_payload(summary_task_callable)
        ),
        "summary_runtime_settings": _summary_runtime_settings_digest(),
        **{
            module_name: _module_implementation_digest(module_name)
            for module_name in _SUMMARY_IMPLEMENTATION_MODULES
        },
    }
    payload = {
        "schema_version": SUMMARY_IMPLEMENTATION_CONTRACT_VERSION,
        "components": components,
    }
    return {**payload, "fingerprint": _fingerprint(payload)}


def build_worker_runtime_contract(
    summary_task_callable: Callable[..., object],
) -> dict[str, Any]:
    request_schema = task_request_schema(summary_task_callable)
    implementation = summary_implementation_contract(summary_task_callable)
    fingerprint_payload = {
        "schema_version": WORKER_RUNTIME_CONTRACT_VERSION,
        "summary_task": {
            "name": SUMMARY_TASK_NAME,
            "request_schema": request_schema,
        },
        "summary_implementation": implementation,
    }
    return {
        **fingerprint_payload,
        "fingerprint": _fingerprint(fingerprint_payload),
    }


def compare_worker_runtime_contracts(
    expected: Mapping[str, Any],
    observed: object,
) -> list[str]:
    if not isinstance(expected, Mapping):
        return ["expected runtime contract is not an object"]
    if not isinstance(observed, Mapping):
        return ["worker returned a non-object runtime contract"]

    errors = [
        *_runtime_contract_structure_errors("expected", expected),
        *_runtime_contract_structure_errors("observed", observed),
    ]
    if observed.get("schema_version") != expected.get("schema_version"):
        errors.append("runtime contract schema version mismatch")
    if observed.get("fingerprint") != expected.get("fingerprint"):
        errors.append("runtime contract fingerprint mismatch")
    if observed.get("summary_task") != expected.get("summary_task"):
        errors.append("summary task request schema mismatch")
    if observed.get("summary_implementation") != expected.get(
        "summary_implementation"
    ):
        errors.append("summary implementation fingerprint mismatch")
    return list(dict.fromkeys(errors))


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _runtime_contract_structure_errors(
    label: str,
    contract: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    required_fields = {
        "schema_version",
        "summary_task",
        "summary_implementation",
        "fingerprint",
    }
    allowed_fields = set(required_fields)
    if label == "observed":
        allowed_fields.add("worker_hostname")
    if not required_fields.issubset(contract) or not set(contract).issubset(
        allowed_fields
    ):
        errors.append(f"{label} runtime contract fields are invalid")
    if "worker_hostname" in contract and not isinstance(
        contract.get("worker_hostname"),
        (str, type(None)),
    ):
        errors.append(f"{label} worker hostname is invalid")
    if contract.get("schema_version") != WORKER_RUNTIME_CONTRACT_VERSION:
        errors.append(f"{label} runtime contract schema version is invalid")

    summary_task = contract.get("summary_task")
    if not isinstance(summary_task, Mapping) or set(summary_task) != {
        "name",
        "request_schema",
    }:
        errors.append(f"{label} summary task contract is invalid")
    else:
        request_schema = summary_task.get("request_schema")
        if (
            summary_task.get("name") != SUMMARY_TASK_NAME
            or not isinstance(request_schema, Mapping)
            or set(request_schema) != {"parameters"}
            or not isinstance(request_schema.get("parameters"), list)
        ):
            errors.append(f"{label} summary task contract is invalid")

    implementation = contract.get("summary_implementation")
    if not isinstance(implementation, Mapping) or set(implementation) != {
        "schema_version",
        "components",
        "fingerprint",
    }:
        errors.append(f"{label} summary implementation contract is invalid")
    else:
        components = implementation.get("components")
        expected_components = {
            "summary_task_callable",
            "summary_runtime_settings",
            *_SUMMARY_IMPLEMENTATION_MODULES,
        }
        if (
            implementation.get("schema_version")
            != SUMMARY_IMPLEMENTATION_CONTRACT_VERSION
            or not isinstance(components, Mapping)
            or set(components) != expected_components
            or any(
                not isinstance(name, str)
                or not isinstance(digest, str)
                or _SHA256_PATTERN.fullmatch(digest) is None
                for name, digest in components.items()
            )
        ):
            errors.append(f"{label} summary implementation contract is invalid")
        else:
            implementation_payload = {
                "schema_version": implementation["schema_version"],
                "components": dict(components),
            }
            if implementation.get("fingerprint") != _fingerprint(
                implementation_payload
            ):
                errors.append(
                    f"{label} summary implementation fingerprint is invalid"
                )

    fingerprint = contract.get("fingerprint")
    if (
        not isinstance(fingerprint, str)
        or _SHA256_PATTERN.fullmatch(fingerprint) is None
    ):
        errors.append(f"{label} runtime contract fingerprint is invalid")
    elif (
        isinstance(summary_task, Mapping)
        and isinstance(implementation, Mapping)
        and fingerprint
        != _fingerprint(
            {
                "schema_version": contract.get("schema_version"),
                "summary_task": dict(summary_task),
                "summary_implementation": dict(implementation),
            }
        )
    ):
        errors.append(f"{label} runtime contract fingerprint is invalid")
    return errors


__all__ = [
    "SUMMARY_TASK_NAME",
    "SUMMARY_IMPLEMENTATION_CONTRACT_VERSION",
    "RuntimeContractUnsupportedState",
    "WORKER_RUNTIME_CONTRACT_TASK",
    "WORKER_RUNTIME_CONTRACT_VERSION",
    "build_worker_runtime_contract",
    "compare_worker_runtime_contracts",
    "summary_implementation_contract",
    "task_request_schema",
]
