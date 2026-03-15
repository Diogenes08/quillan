"""Topological sort of beat dependency graph → independent batches.

Each batch is a list of beat IDs that can run in parallel.
Batches must be processed sequentially (each batch depends on the previous).
"""

from __future__ import annotations


class CycleError(Exception):
    """Raised when the dependency graph contains a cycle."""


def compute_dependents(deps_raw: dict, start_beats: list[str]) -> list[str]:
    """Return sorted list of all beats that transitively depend on any start beat.

    Includes start_beats themselves. Uses BFS over the successor adjacency list
    (the reverse of the deps dict). Accepts wrapped or raw dep_map format.

    Unknown start beat IDs that are not in the dep map are silently ignored.
    """
    # Accept either the full dep_map wrapper or the raw dependencies dict
    if "dependencies" in deps_raw and isinstance(deps_raw["dependencies"], dict):
        deps = deps_raw["dependencies"]
    else:
        deps = deps_raw

    all_nodes = set(deps.keys())

    # Build successors dict (reverse of deps): pred → [nodes that depend on pred]
    successors: dict[str, list[str]] = {node: [] for node in all_nodes}
    for node, predecessors in deps.items():
        for pred in predecessors:
            if pred in all_nodes:
                successors[pred].append(node)

    # BFS from start_beats, following successor edges
    visited: set[str] = set()
    queue: list[str] = []
    for bid in start_beats:
        if bid in all_nodes and bid not in visited:
            visited.add(bid)
            queue.append(bid)

    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        for succ in successors.get(node, []):
            if succ not in visited:
                visited.add(succ)
                queue.append(succ)

    return sorted(visited)


def compute_batches(dep_map: dict) -> list[list[str]]:
    """Standard indegree-reduction DAG → list of independent batches.

    Args:
        dep_map: A dict like {"dependencies": {"B1": [], "B2": ["B1"], ...}}
                 OR the raw dependencies dict {"B1": [], "B2": ["B1"], ...}

    Returns:
        A list of batches. Each batch is a sorted list of beat IDs
        that can run in parallel. Batches must be processed sequentially.

    Raises:
        CycleError: if the graph contains a cycle.
        ValueError: if a dependency references an unknown beat ID.
    """
    # Accept either the full dep_map wrapper or the raw dependencies dict
    if "dependencies" in dep_map and isinstance(dep_map["dependencies"], dict):
        deps = dep_map["dependencies"]
    else:
        deps = dep_map

    if not deps:
        return []

    # Validate: all referenced nodes must be declared
    all_nodes = set(deps.keys())
    for node, predecessors in deps.items():
        for pred in predecessors:
            if pred not in all_nodes:
                raise ValueError(
                    f"Beat '{node}' depends on undeclared beat '{pred}'"
                )

    # Build indegree count and adjacency list
    indegree: dict[str, int] = {node: 0 for node in all_nodes}
    successors: dict[str, list[str]] = {node: [] for node in all_nodes}

    for node, predecessors in deps.items():
        indegree[node] += len(predecessors)
        for pred in predecessors:
            successors[pred].append(node)

    batches: list[list[str]] = []
    remaining = set(all_nodes)

    while remaining:
        # Collect all nodes with no remaining dependencies
        ready = sorted(
            node for node in remaining if indegree[node] == 0
        )
        if not ready:
            cycle_nodes = sorted(remaining)
            raise CycleError(
                f"Dependency cycle detected among beats: {cycle_nodes}"
            )

        batches.append(ready)

        # Remove ready nodes and update indegrees
        for node in ready:
            remaining.remove(node)
            for succ in successors[node]:
                indegree[succ] -= 1

    return batches
