"""DAG scheduler: find ready tasks within a module."""
from models import Module, ModuleStatus, Task, TaskStatus


def get_ready_tasks(
    tasks: list[Task], max_parallel: int = 5, completed_ids: set[str] | None = None,
) -> list[Task]:
    """Find tasks whose dependencies are all merged."""
    satisfied_ids = {t.id for t in tasks if t.status == TaskStatus.MERGED}
    if completed_ids:
        satisfied_ids.update(completed_ids)
    ready = []

    for task in tasks:
        if task.status != TaskStatus.PENDING:
            continue
        if all(dep in satisfied_ids for dep in task.dependencies):
            task.status = TaskStatus.READY
            ready.append(task)
        if len(ready) >= max_parallel:
            break

    return ready


def module_done(module: Module) -> bool:
    """Check if all tasks in a module are terminal."""
    return all(
        t.status in (TaskStatus.MERGED, TaskStatus.FAILED)
        for t in module.tasks
    )


def module_stats(module: Module) -> dict[str, int]:
    """Get task count by status for a module."""
    from collections import Counter
    counts = Counter(t.status.value for t in module.tasks)
    return dict(counts)


def all_modules_done(modules: list[Module]) -> bool:
    """Check if all modules are terminal."""
    return all(
        m.status in (ModuleStatus.PASSED, ModuleStatus.FAILED)
        for m in modules
    )


def overall_stats(modules: list[Module]) -> dict[str, int]:
    """Get aggregate task stats across all modules."""
    from collections import Counter
    counts = Counter()
    for m in modules:
        for t in m.tasks:
            counts[t.status.value] += 1
    return dict(counts)
