"""Fees seed: writes real-shaped SCOPE fee/finance blobs onto the shared test
user (tests/_seed.py base user), so the Fees tab renders with no network.

Two arms, chosen by argv[1]:
  dues   - one unpaid fee head (tuition 200000 vs 100000 paid) -> hero present
  clear  - every head paid == total, trailing 0      -> hero absent, page
           starts at Paid (the all-clear widget was removed)
Receipts are the mission's verbatim finance fixture (6 rows, PayU/IMPS
narrations) so the collapsed receipt rows are measured on real text.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _seed  # noqa: E402  (tests/ root)

FIN = [
    {"amount": "111000.00", "vouchertype": "Receipt", "voucherdate": "2025-11-21",
     "vouchernumber": "17174",
     "narration": "being recd. fee for the yr.2025-26 THRU 08-08-2025\t\tIMPS/P2A/522013235148/UMASHANK/ICICIBAN/SRMFinal/9197174947749229369\t111000\r\n\r\n\r\n"},
    {"amount": "4050.00", "vouchertype": "Receipt", "voucherdate": "2025-11-26",
     "vouchernumber": "17720",
     "narration": "Being Fee received from student for Exam Fees fee paid through online using Pay U (Axis) with bank transaction id 1116435793 on 2025-11-23 23:53:02.177"},
    {"amount": "10000.00", "vouchertype": "Receipt", "voucherdate": "2025-11-27",
     "vouchernumber": "19090",
     "narration": "Being Admission FEE  for the academic year 2025 - 2026  Accounted with bank transaction id 520623190760 on 2025-07-25"},
    {"amount": "100000.00", "vouchertype": "Receipt", "voucherdate": "2025-11-27",
     "vouchernumber": "19091",
     "narration": "Being Admission FEE  for the academic year 2025 - 2026  Accounted with bank transaction id 520715160725 on 2025-07-26"},
    {"amount": "2950.00", "vouchertype": "Receipt", "voucherdate": "2026-05-04",
     "vouchernumber": "22150",
     "narration": "Being Fee received from student for Exam Fees fee paid through online using Razorpay with bank transaction id - on 2026-05-03 13:55:10.436"},
    {"amount": "200000.00", "vouchertype": "Receipt", "voucherdate": "2026-07-02",
     "vouchernumber": "8162",
     "narration": "Being Fee received from student for College Fees fee paid through online using Pay U (Axis) with bank transaction id 1221229971 on 2026-06-29 23:13:37.86"},
]

DUES_FEES = [
    {"feedetails": "Registration Fee##10000.00##10000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Tuition Fees##100000.00##200000.00##13-Aug-2025##2025-2026##100000"},
    {"feedetails": "Exam Fees##3150.00##3150.00##13-Aug-2025##2025-2026##0"},
]
CLEAR_FEES = [
    {"feedetails": "Registration Fee##10000.00##10000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Tuition Fees##200000.00##200000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Exam Fees##3150.00##3150.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Hostel Fees##45000.00##45000.00##21-Jan-2026##2025-2026##0"},
]


def seed(arm="clear"):
    _seed.seed()
    from app import app as A
    scope = {
        "getFeeDetails": {"data": DUES_FEES if arm == "dues" else CLEAR_FEES, "ts": 1},
        "getFinanceDetails": {"data": FIN, "ts": 1},
    }
    c = A.db()
    c.execute("UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid='zz9999'",
              (json.dumps(scope), 1))
    c.commit()
    c.close()


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else "clear")
    print("fees seed ok")
