"""DMS Analytics modules package — all flags."""
from .secondary_sales import SECONDARY_SALES_FLAGS
from .purchases import PURCHASES_FLAGS
from .primary_sales import PRIMARY_SALES_FLAGS
from .combined import COMBINED_FLAGS
from .stock_clearance import STOCK_CLEARANCE_FLAGS
from .stock_movement import STOCK_MOVEMENT_FLAGS

from .schemes import SCHEMES_FLAGS
from .claims import CLAIMS_FLAGS
from .masters import MASTERS_FLAGS

ALL_FLAGS = {
    **SECONDARY_SALES_FLAGS,
    **PURCHASES_FLAGS,
    **PRIMARY_SALES_FLAGS,
    **COMBINED_FLAGS,
    **STOCK_CLEARANCE_FLAGS,
    **STOCK_MOVEMENT_FLAGS,
    **SCHEMES_FLAGS,
    **CLAIMS_FLAGS,
    **MASTERS_FLAGS,
}
