"""Version-conformance tests for mem0ai==2.0.19 private/internal API couplings.

``memory/mem0_wrapper.py`` reaches past mem0's documented public entry point
(``mem0.Memory``/``mem0.AsyncMemory`` constructed from a plain dict config)
into several private or internal surfaces: an import-time telemetry flag, a
subclassed abstract base class, a monkey-patched module global, and a set of
internal config/factory classes constructed directly via ``model_construct``
to bypass validators that would otherwise reject this project's custom
"sqlite_vec"/"jarvis_local" providers.

Only one of these couplings (the missing ``VectorStoreBase`` import) already
fails loudly with an ``ImportError`` on a version bump that removes it. Every
other coupling here would silently change behavior instead: a renamed
telemetry flag stops disabling telemetry, a changed
``ADDITIVE_EXTRACTION_PROMPT`` guard-length invariant lets the wrapper patch
a prompt mem0 already shortened (or refuse to patch one that changed shape),
a validator that starts accepting "sqlite_vec"/"jarvis_local" natively (or
stops rejecting them) changes whether ``model_construct`` is still the right
tool, and a ``provider_to_class`` dict that becomes immutable or renamed
breaks the wrapper's provider registration with no import-time signal at all.

Each test below imports one exact symbol from the brief and asserts something
about its shape empirically confirmed against the installed mem0ai==2.0.19
(see ``docs/consults`` / lane brief for the verification transcript) so that
upgrading mem0ai and running this file specifically is what fails loudly for
every one of these couplings, not just the one that already does.
"""

from __future__ import annotations

import importlib.metadata
import inspect
from abc import ABC

import pytest
from pydantic import ValidationError

from memory.mem0_wrapper import _SHIPPED_PROMPT_MINIMUM_LENGTH, SQLiteVecMem0Store


def test_mem0ai_is_still_pinned_to_the_version_every_other_test_here_assumes():
    assert importlib.metadata.version("mem0ai") == "2.0.19"


def test_mem0_telemetry_flag_is_a_module_level_boolean_read_from_the_environ_at_import_time():
    # memory/mem0_wrapper.py sets os.environ["MEM0_TELEMETRY"] = "False" before
    # importing mem0 anywhere, relying on mem0.memory.telemetry reading that
    # env var into a module-global bool exactly once, at import time. If mem0
    # renames the env var, renames the module attribute, or starts reading it
    # lazily instead, telemetry silently stops being disabled.
    import mem0.memory.telemetry as telemetry

    assert isinstance(telemetry.MEM0_TELEMETRY, bool)
    assert hasattr(telemetry, "PROJECT_API_KEY")  # confirms this is still the posthog-backed module we expect


def test_vector_store_base_still_declares_exactly_the_abstract_surface_the_wrapper_implements():
    from mem0.vector_stores.base import VectorStoreBase

    assert issubclass(VectorStoreBase, ABC)
    # SQLiteVecMem0Store subclasses this directly instead of going through any
    # documented public provider-registration entry point. If mem0 adds a new
    # abstractmethod, SQLiteVecMem0Store silently becomes uninstantiable (a
    # TypeError far from this file); if mem0 removes one, the wrapper is
    # implementing dead surface without saying so. Either way this must be
    # exactly the set below, not a superset or subset.
    assert VectorStoreBase.__abstractmethods__ == frozenset(
        {
            "create_col",
            "insert",
            "search",
            "delete",
            "update",
            "get",
            "list_cols",
            "delete_col",
            "col_info",
            "list",
            "reset",
        }
    )


def test_sqlite_vec_store_implements_every_abstract_method_vector_store_base_currently_requires():
    from mem0.vector_stores.base import VectorStoreBase

    assert issubclass(SQLiteVecMem0Store, VectorStoreBase)
    missing = VectorStoreBase.__abstractmethods__ - set(dir(SQLiteVecMem0Store))
    assert not missing


def test_additive_extraction_prompt_exists_and_still_clears_the_wrappers_own_length_guard():
    # The wrapper's _install_compact_extraction_prompt() refuses to patch a
    # prompt shorter than _SHIPPED_PROMPT_MINIMUM_LENGTH, on the theory that a
    # shipped prompt that short means mem0 already changed the extraction
    # design out from under this pin. Confirm the currently pinned version
    # still clears that guard, so a future mem0ai bump that shrinks the
    # prompt is caught here rather than only at first live Memory.add() call.
    import mem0.memory.main as mem0_main

    assert isinstance(mem0_main.ADDITIVE_EXTRACTION_PROMPT, str)
    assert len(mem0_main.ADDITIVE_EXTRACTION_PROMPT) >= _SHIPPED_PROMPT_MINIMUM_LENGTH


def test_memory_add_and_async_memory_add_both_still_read_the_prompt_as_a_bare_module_global():
    # The wrapper's patch (mem0_main.ADDITIVE_EXTRACTION_PROMPT = ...) only
    # works because both Memory.add and AsyncMemory.add eventually call into
    # a same-named private helper (_add_to_vector_store, the "V3 phased batch
    # pipeline" the wrapper's own comment describes) that resolves
    # ADDITIVE_EXTRACTION_PROMPT unqualified against mem0.memory.main's own
    # module namespace at call time, not a value captured at class-definition
    # time or imported fresh from mem0.configs.prompts on every call. If a
    # future mem0ai version renames/inlines that helper, binds the prompt to
    # a local variable, or reimports it per-call from another module, the
    # wrapper's module-level reassignment stops reaching either add() path
    # silently.
    import mem0.memory.main as mem0_main

    add_source = inspect.getsource(mem0_main.Memory.add)
    async_add_source = inspect.getsource(mem0_main.AsyncMemory.add)
    assert "_add_to_vector_store" in add_source
    assert "_add_to_vector_store" in async_add_source

    add_to_vector_store_source = inspect.getsource(mem0_main.Memory._add_to_vector_store)
    async_add_to_vector_store_source = inspect.getsource(mem0_main.AsyncMemory._add_to_vector_store)
    assert "ADDITIVE_EXTRACTION_PROMPT" in add_to_vector_store_source
    assert "ADDITIVE_EXTRACTION_PROMPT" in async_add_to_vector_store_source


def test_vector_store_config_still_rejects_the_custom_sqlite_vec_provider_through_normal_construction():
    # This is the validator model_construct exists to bypass. If mem0 ever
    # allows unregistered/third-party providers here, the wrapper's use of
    # model_construct (which also skips *all other* field validation) has
    # become an unnecessarily broad bypass and should be narrowed.
    from mem0.vector_stores.configs import VectorStoreConfig

    with pytest.raises(ValidationError, match="Unsupported vector store provider"):
        VectorStoreConfig(provider="sqlite_vec", config={})


def test_vector_store_config_model_construct_still_bypasses_that_validator():
    from mem0.vector_stores.configs import VectorStoreConfig

    config = VectorStoreConfig.model_construct(provider="sqlite_vec", config={"a": 1})
    assert config.provider == "sqlite_vec"
    assert config.config == {"a": 1}


def test_embedder_config_still_rejects_the_custom_jarvis_local_provider_through_normal_construction():
    from mem0.embeddings.configs import EmbedderConfig

    with pytest.raises(ValidationError, match="Unsupported embedding provider"):
        EmbedderConfig(provider="jarvis_local", config={})


def test_embedder_config_model_construct_still_bypasses_that_validator():
    from mem0.embeddings.configs import EmbedderConfig

    config = EmbedderConfig.model_construct(provider="jarvis_local", config={"model": "nomic-embed-text"})
    assert config.provider == "jarvis_local"
    assert config.config == {"model": "nomic-embed-text"}


def test_llm_config_still_accepts_ollama_through_normal_construction_without_needing_a_bypass():
    # Unlike vector_store/embedder, memory/mem0_wrapper.py constructs LlmConfig
    # normally (LlmConfig(provider="ollama", ...), no model_construct) because
    # "ollama" is one of mem0's supported providers. If a future mem0ai
    # version drops "ollama" from the accepted set, this call starts raising
    # at Memory() construction time; confirm the assumption here instead of
    # only discovering it live.
    from mem0.llms.configs import LlmConfig

    config = LlmConfig(provider="ollama", config={"model": "llama3.1:8b"})
    assert config.provider == "ollama"


def test_memory_config_still_re_validates_nested_submodels_so_the_outer_model_construct_is_still_needed():
    # Passing already-bypassed VectorStoreConfig/EmbedderConfig instances into
    # a normally-constructed MemoryConfig(...) still re-runs their field
    # validators in the installed pydantic/mem0ai combination, so
    # open_mem0_memory() must also build the outer MemoryConfig via
    # model_construct, not just the two inner configs. If a future
    # mem0ai/pydantic combination stops re-validating already-built nested
    # models, the outer model_construct call becomes unnecessary but this
    # test would start failing (no ValidationError raised) rather than the
    # assumption silently going stale.
    from mem0.configs.base import MemoryConfig
    from mem0.embeddings.configs import EmbedderConfig
    from mem0.llms.configs import LlmConfig
    from mem0.vector_stores.configs import VectorStoreConfig

    vector_store = VectorStoreConfig.model_construct(provider="sqlite_vec", config={"a": 1})
    embedder = EmbedderConfig.model_construct(provider="jarvis_local", config={"model": "x"})
    llm = LlmConfig(provider="ollama", config={"model": "llama3.1:8b"})

    with pytest.raises(ValidationError, match="Unsupported vector store provider"):
        MemoryConfig(vector_store=vector_store, embedder=embedder, llm=llm)

    constructed = MemoryConfig.model_construct(
        vector_store=vector_store, embedder=embedder, llm=llm, history_db_path="x"
    )
    assert constructed.vector_store.provider == "sqlite_vec"
    assert constructed.embedder.provider == "jarvis_local"
    assert constructed.llm.provider == "ollama"


def test_vector_store_factory_provider_to_class_is_still_a_plain_mutable_dict_keyed_by_provider_name():
    # _register_mem0_factories() mutates VectorStoreFactory.provider_to_class
    # in place (vector_factory.provider_to_class["sqlite_vec"] = "...") rather
    # than calling any documented registration function. If mem0 ever
    # replaces this with an immutable mapping, a copy-on-read property, or a
    # differently named attribute, that mutation becomes either a no-op or an
    # AttributeError far from this file.
    from mem0.utils.factory import VectorStoreFactory

    assert isinstance(VectorStoreFactory.provider_to_class, dict)
    assert "qdrant" in VectorStoreFactory.provider_to_class  # a known shipped provider is still resolved by string key


def test_embedder_factory_provider_to_class_is_still_a_plain_mutable_dict_keyed_by_provider_name():
    from mem0.utils.factory import EmbedderFactory

    assert isinstance(EmbedderFactory.provider_to_class, dict)
    assert "ollama" in EmbedderFactory.provider_to_class


def test_vector_store_factory_create_still_resolves_a_registered_provider_by_dotted_class_path_and_kwargs():
    # Confirms the exact call shape _register_mem0_factories() relies on:
    # a string "module.Class" value in provider_to_class, resolved through
    # importlib and instantiated with the stored config unpacked as kwargs
    # (not passed as a single positional config object). SQLiteVecMem0Store's
    # __init__ signature (collection_name, embedding_model_dims,
    # database_path, embedding_model, **_) depends on this being **kwargs.
    from mem0.utils.factory import VectorStoreFactory

    # bound classmethod: inspect.signature omits the implicit "cls" parameter.
    params = list(inspect.signature(VectorStoreFactory.create).parameters)
    assert params == ["provider_name", "config"]

    original = dict(VectorStoreFactory.provider_to_class)
    try:
        VectorStoreFactory.provider_to_class["sqlite_vec"] = "memory.mem0_wrapper.SQLiteVecMem0Store"
        store = VectorStoreFactory.create(
            "sqlite_vec",
            {
                "collection_name": "jarvis_memories",
                "embedding_model_dims": 2,
                "database_path": ":memory:",
                "embedding_model": "nomic-embed-text",
            },
        )
        assert isinstance(store, SQLiteVecMem0Store)
        store.close()
    finally:
        VectorStoreFactory.provider_to_class.clear()
        VectorStoreFactory.provider_to_class.update(original)


def test_embedder_factory_create_signature_still_takes_provider_config_and_vector_config_positionally():
    # memory/mem0_wrapper.py never calls EmbedderFactory.create() itself --
    # mem0.memory.main.Memory.__init__ does, positionally, as
    # EmbedderFactory.create(provider, embedder_config, vector_store_config).
    # A signature change here (param renamed, reordered, or an added required
    # kwarg) would break LocalMem0Embedding's registration only inside a live
    # Memory() construction, never at import time.
    from mem0.utils.factory import EmbedderFactory

    # bound classmethod: inspect.signature omits the implicit "cls" parameter.
    params = list(inspect.signature(EmbedderFactory.create).parameters)
    assert params == ["provider_name", "config", "vector_config"]
