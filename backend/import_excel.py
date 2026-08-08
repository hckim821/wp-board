"""엑셀 → DB 초기값 임포트 (백엔드 최상단 진입점).

``docs/Work Package.xlsx`` 의 **Project Board** 시트(35행)와 **Doc Status**
시트(5행)를 읽어 `iai-test` DB 에 초기값으로 적재한다. 양식은 현재 엑셀
레이아웃 그대로 고정이다 — 컬럼 순서/헤더가 바뀌면 파싱이 실패하도록 되어 있다.

실제 파싱·적재 로직은 ``db/migrate.py`` 한 곳에만 있다 (원문자 ①~⑤ 토큰화,
Phase/Milestone 번호 분리, `+` Owner 분리, 연속성 검사 등). 이 파일은 그
구현을 백엔드 폴더에서 바로 실행할 수 있게 하는 진입점이며, 규칙을 여기에
복제하지 않는다 — 두 벌이 되는 순간 드리프트가 시작된다.

사용법 (backend/ 에서, 3.11+ 환경)::

    python import_excel.py               # schema.sql 적용 + 엑셀 적재
    python import_excel.py --dry-run     # DB 를 건드리지 않고 파싱 검사만
    python import_excel.py --emit-sql    # db/seed.sql 재생성 (SQL 산출물 갱신)
    python import_excel.py --skip-schema # 스키마 적용 없이 데이터만 재적재
    python import_excel.py --with-dev-seed  # 데모 설비사/프로젝트(dev_seed)도 적용

⚠️ 재적재는 템플릿(DSEP-AI-BOARD)과 그 버전/행을 지우고 다시 만든다.
   실사용 데이터가 쌓인 뒤에는 --dry-run / --emit-sql 외의 실행에 주의할 것
   (HANDOFF.md §0.5). 적재 후 확인은 ``python ../db/verify.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_PATH = REPO_ROOT / "db" / "migrate.py"


def _load_migrate():
    spec = importlib.util.spec_from_file_location("wp_migrate", MIGRATE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    sys.exit(_load_migrate().main(sys.argv[1:]))
