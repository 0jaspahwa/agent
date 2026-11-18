"""Where the task kit lives, and the one fact about it that the CSVs do not contain.

The kit is not in the repo (the task rules). Put its folders in data/ (or point DATA_DIR elsewhere), or upload
the kit zip in the app under Load kit data (services/kit.py)."""
import os
from datetime import date
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR") or Path(__file__).resolve().parents[1] / "data")

# The kit's README.txt: "contract register and contract lines (as at 31 Oct 2026)". The register's consumed
# values are as at this date; contracts signed later exist only as PDFs and start at zero (policy 4.2, 4.4).
REGISTER_AS_OF = date(2026, 10, 31)

# The kit files the app needs, at their place in the kit. The contract PDFs go in contracts/pdf/.
KIT_CSVS = ("master_data/item_master.csv", "master_data/supplier_master.csv", "master_data/plants.csv",
            "master_data/po_history.csv", "contracts/contract_register.csv", "contracts/contract_lines.csv")

NO_KIT_NOTICE = "No kit data loaded. Procurement: load it under Load kit data."


def kit_present(data_dir=DATA_DIR):
    """True if data_dir holds every kit CSV the app needs."""
    return all((Path(data_dir) / rel).is_file() for rel in KIT_CSVS)
