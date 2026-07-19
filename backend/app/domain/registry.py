"""Model registry.

Importing this module imports every domain's ``models`` module, which registers
all ORM tables on ``Base.metadata``. ``database.create_all`` relies on this so
table creation never misses a domain.
"""

from __future__ import annotations

from app.domain.candidates import models as candidate_models  # noqa: F401
from app.domain.companies import models as company_models  # noqa: F401
from app.domain.documents import models as document_models  # noqa: F401
from app.domain.jobs import models as job_models  # noqa: F401
from app.domain.matching import models as matching_models  # noqa: F401
from app.domain.pipeline import models as pipeline_models  # noqa: F401
from app.domain.tenants import models as tenant_models  # noqa: F401
from app.domain.verification import models as verification_models  # noqa: F401