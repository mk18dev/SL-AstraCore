from astra.resolver.import_resolver import safe_module, resolve_imports_into_edges
from astra.ir.models import (
    EdgeType,
    IRDependency,
    IRFileNode,
    IRFileParseResult,
    NodeType,
    FileRole,
)


def _make_result(path: str, deps: list[IRDependency] | None = None) -> IRFileParseResult:
    return IRFileParseResult(
        file_path=path,
        language="python",
        file_node=IRFileNode(
            id=f"file:{path}",
            type=NodeType.FILE,
            name=path.split("/")[-1],
            source="parser",
            file_path=path,
            language="python",
            role=FileRole.UNKNOWN,
            line_count=10,
            byte_size=100,
            confidence=0.9,
        ),
        dependencies=tuple(deps or []),
    )


def test_safe_module_convention():
    assert safe_module("src/services", "auth") == "src.services.auth"
    assert safe_module("/src/services", "auth") == "src.services.auth"
    assert safe_module("", "app") == "app"


def test_resolve_local_module_import():
    result = _make_result(
        "src/main.py",
        deps=[
            IRDependency(
                source_file="src/main.py",
                target_module="utils",
                kind="import",
                line=1,
            ),
        ],
    )

    target = _make_result("src/utils.py")

    _, edges = resolve_imports_into_edges([result, target])

    assert len(edges) == 1
    assert edges[0].from_node == "src/main.py"
    assert edges[0].to_node == "src/utils.py"
    assert edges[0].type == EdgeType.IMPORTS


def test_resolve_absolute_module():
    result = _make_result(
        "src/app.py",
        deps=[
            IRDependency(
                source_file="src/app.py",
                target_module="src.services.auth",
                kind="import",
                line=1,
            ),
        ],
    )

    target = _make_result("src/services/auth.py")
    targets_dep = _make_result("src/services/__init__.py")

    _, edges = resolve_imports_into_edges([result, target, targets_dep])

    assert len(edges) == 1
    assert edges[0].to_node == "src/services/auth.py"


def test_unresolvable_import_produces_no_edge():
    result = _make_result(
        "src/main.py",
        deps=[
            IRDependency(
                source_file="src/main.py",
                target_module="nonexistent",
                kind="import",
                line=1,
            ),
        ],
    )

    _, edges = resolve_imports_into_edges([result])

    assert edges == ()


def test_idempotent_resolution():
    result = _make_result(
        "src/main.py",
        deps=[
            IRDependency(
                source_file="src/main.py",
                target_module="utils",
                kind="import",
                line=1,
            ),
        ],
    )
    target = _make_result("src/utils.py")

    first = resolve_imports_into_edges([result, target])
    second = resolve_imports_into_edges([result, target])

    assert first == second



def test_duplicate_basenames_resolve_using_source_directory():
    auth_main = _make_result(
        "src/auth/main.py",
        [IRDependency(source_file="src/auth/main.py", target_module="utils", kind="import", line=1)],
    )
    auth_utils = _make_result("src/auth/utils.py")
    payment_utils = _make_result("src/payment/utils.py")

    _, edges = resolve_imports_into_edges([auth_main, auth_utils, payment_utils])

    assert len(edges) == 1
    assert edges[0].to_node == "src/auth/utils.py"


def test_ambiguous_bare_import_is_not_resolved_to_arbitrary_package():
    main = _make_result(
        "src/main.py",
        [IRDependency(source_file="src/main.py", target_module="utils", kind="import", line=1)],
    )
    auth_utils = _make_result("src/auth/utils.py")
    payment_utils = _make_result("src/payment/utils.py")

    resolved, edges = resolve_imports_into_edges([main, auth_utils, payment_utils])

    assert resolved["utils"] == ""
    assert edges == ()


def test_package_import_resolves_to_its_init_file():
    main = _make_result(
        "src/main.py",
        [IRDependency(source_file="src/main.py", target_module="src.services", kind="import", line=1)],
    )
    package = _make_result("src/services/__init__.py")
    service = _make_result("src/services/auth.py")

    _, edges = resolve_imports_into_edges([main, package, service])

    assert len(edges) == 1
    assert edges[0].to_node == "src/services/__init__.py"
