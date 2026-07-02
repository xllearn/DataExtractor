from dataclasses import dataclass
from pathlib import Path

from config import PROJECT_ROOT
from utils import ensure_dir


@dataclass(frozen=True)
class RunContext:
    output_dir: Path
    log_dir: Path
    temp_images_dir: Path
    template_path: Path

    @classmethod
    def from_roots(
        cls,
        output_dir: str | Path,
        log_dir: str | Path,
        temp_images_dir: str | Path | None = None,
        template_path: str | Path | None = None,
    ) -> "RunContext":
        output_root = _resolve_project_path(output_dir)
        log_root = _resolve_project_path(log_dir)
        temp_root = _resolve_project_path(temp_images_dir or PROJECT_ROOT / "temp_images")
        template = _resolve_project_path(template_path or PROJECT_ROOT / "templates" / "template.xlsx")
        ensure_dir(output_root)
        ensure_dir(log_root)
        ensure_dir(temp_root)
        return cls(output_dir=output_root, log_dir=log_root, temp_images_dir=temp_root, template_path=template)

    def job_log_dir(self, job_id: str | None) -> Path:
        if job_id:
            return ensure_dir(self.log_dir / job_id)
        return ensure_dir(self.log_dir)


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
