"""Fees seed: writes real-shaped SCOPE fee/finance blobs onto the shared test
user (tests/_seed.py base user), so the Fees tab renders with no network.

Arms, chosen by argv[1]:
  dues    - one unpaid fee head (tuition 200000 vs 100000 paid) -> a named
            charge with no deadline, since a fee row carries none
  clear   - every head paid == total, trailing 0 -> "Nothing due.", page
            starts at the Paid header
  exam    - the REAL 2026-11-04 shape: every head shows paid == total and
            trailing 0, while getStudentExamFeesDetails says 3150 is owed and
            due 25-11-2026. Before the fix this rendered "no dues".
  live    - the FULL 2026-11-26 exam-fee shape: feetype, the cheap-payment
            deadline (05-12), the penalty date (06-12) and the total with the
            late fee -> the coming-soon card, "N days left", "+1,000 from"
  overdue - the same row with both dates already past and penaltystatus=1
            -> "overdue", "was due", "late fee applied"
  multi   - a trailing-based charge next to the exam one -> the "Owed" sum
            line appears (2 charges; with 1 it would be a duplicate)
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


# verbatim live getStudentExamFeesDetails row (2026-11-04, netid ng2776)
EXAM_DUES = [{"partpaymentapplicable": 0, "studentname": "NAVYA GUPTA",
              "startdate": "21-09-2026", "minamount": 3150, "amounttopay": 3150,
              "studentid": "709245", "paidamount": 0, "enddate": "25-11-2026",
              "penaltystatus": 0, "sno": "2440869", "officeid": "20",
              "amountwithoutpenalty": 3150, "penaltydate": "24-11-2026",
              "ischeckvisible": "t", "appln_category_id": "1"}]


# the full live shape (2026-11-26): the page's deadline pair comes from the
# last two fields here, and are what the old view threw away
def _live(deadline, penalty_on, penalised=0):
    return [{"academicyear": "NOVEMBER-2026", "studentname": "NAVYA GUPTA",
             "minamount": 3150, "concessionamount": 0, "amounttopay": 3150,
             "paidamount": 0, "studentid": "709245", "enddate": penalty_on,
             "penaltystatus": penalised, "penaltyamount": 1000, "sno": "2440869",
             "officeid": "20", "amountwithoutpenalty": 3150, "feetype": "Exam Fees",
             "feetypeid": "2", "ischeckvisible": "t", "penaltydate": penalty_on,
             "lastdateforfeepaymentwithoutlatefee": deadline,
             "feewithlatefee": 4150}]


LIVE_DUES = _live("05-12-2026", "06-12-2026")
OVERDUE_DUES = _live("22-11-2026", "23-11-2026", penalised=1)

# one head short by 100000: this row's own trailing/total disagrees, so it
# becomes its own named charge (dateless) next to the exam one
SHORT_FEES = [
    {"feedetails": "Registration Fee##10000.00##10000.00##13-Aug-2025##2025-2026##0"},
    {"feedetails": "Tuition Fees##100000.00##200000.00##13-Aug-2025##2025-2026##100000"},
    # a second academic year: the only case where a year header row exists
    {"feedetails": "Exam Fees##3150.00##3150.00##24-Sep-2026##2026-2027##0"},
]


def seed(arm="clear"):
    _seed.seed()
    from app import app as A
    scope = {
        "getFeeDetails": {"data": DUES_FEES if arm == "dues" else
                          SHORT_FEES if arm == "multi" else CLEAR_FEES, "ts": 1},
        "getFinanceDetails": {"data": FIN, "ts": 1},
    }
    if arm == "exam":
        scope["getStudentExamFeesDetails"] = {"data": EXAM_DUES, "ts": 1}
    elif arm == "live":
        scope["getStudentExamFeesDetails"] = {"data": LIVE_DUES, "ts": 1}
    elif arm == "multi":
        scope["getStudentExamFeesDetails"] = {"data": LIVE_DUES, "ts": 1}
    elif arm == "overdue":
        scope["getStudentExamFeesDetails"] = {"data": OVERDUE_DUES, "ts": 1}
    c = A.db()
    c.execute("UPDATE users SET scope_json=?, scope_fetched_at=? WHERE netid='zz9999'",
              (json.dumps(scope), 1))
    c.commit()
    c.close()


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else "clear")
    print("fees seed ok")
