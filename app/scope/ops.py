"""SCOPE op catalog + feature-toggle registry.

OPS = the 43-op catalog copied verbatim from fixtures/ops.json (mission dir
scope-integration; XSD-verified against the live WSDL 2026-10-18).

FEATURES = feature slug -> ops it enables. Every SCOPE feature ships, gated
by toggles (mission FACTS, user decision): unused-now features are fully
supported but off until enabled. attendance + marks are the portal-parity
fallback sources - enabled by default but UI-neutral. placement / library /
campus are implemented end to end but DEFAULT-OFF: their SCOPE payloads are
alive-empty for every student today, so they stay dark until the portal
operation mapping is mapped out and someone opts in. The exam-details /
timetable JSP is deliberately NOT duplicated as a feature: the timetable
stays portal-owned.

Env toggle SCOPE_FEATURES (app/config.py request-time-knob pattern): comma
slugs, "all" = every feature, "off"/"" = nothing (feature fully off),
unknown slug = logged warning + ignored, unset = DEFAULT_FEATURES.
"""
import logging
import os

log = logging.getLogger("opensrm.scope")

# copied from fixtures/ops.json - keep in sync with the WSDL if it ever moves
OPS = {
    "ChangeUserPassword": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "oldpassword",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "newpassword",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "confirmnewpassword",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getCummulativeAttendance": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getExamDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getFeeDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getFinanceDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getHostelDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getHourwiseAttendance": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getInternalMarkDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getJobCriteria": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getJobQuestions": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getLibraryTransaction": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getOngoingSelectionProcess": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getParentLogin": [
        {
            "name": "parentmobilenumeroremailid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getPersonalDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getPlacementRegistrationDetailsList": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "argtype",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "officeid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getPlacementWillingnessRegistrationOpen": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "officeid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getProgramSubCategoryWiseSubjects": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getQuestionAnswers": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "questionid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getResumeAttachmentView": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getResumeUploads": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentAllOfferedJobs": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentAnswers": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "questionid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentExamProvisionalResult": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentExamRevaluationResult": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentLogin": [
        {
            "name": "username",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "password",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "accesstoken",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentPhoto": [
        {
            "name": "arg0",
            "type": "long",
            "minOccurs": "1"
        }
    ],
    "getStudentPlacementPolicyStatus": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentPlacementRequired": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentTextAnswer": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "questionid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getStudentYesNoAnswer": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "questionid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getSubCategorySemesterWiseStatus": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getSubCategoryWiseStatus": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getSubjects": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getSubjectwiseAttendance": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getTransportDetails": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getViewNotificationListJson": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "getWillingnessRejectReasons": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "savePlacementWillingnessPayment": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "savePlacementWillingnessRequired": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "ipaddress",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "placementwillingnessrequiredstatus",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "reasonid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "saveStudentPlacementRegistration": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "jobid",
            "type": "long",
            "minOccurs": "1"
        },
        {
            "name": "ipaddress",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "attachments",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "questionanswersdata",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "sendOTP": [
        {
            "name": "parentstudentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "inputtype",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "Studentofficeid",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "parentmobilenumeroremailid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "accesstoken",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "updateAccessToken": [
        {
            "name": "studentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "accesstoken",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ],
    "validateOTP": [
        {
            "name": "otp",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentstudentid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "androidversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "model",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "sdkversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "appversion",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "deviceid",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "accesstoken",
            "type": "string",
            "minOccurs": "0"
        },
        {
            "name": "parentflag",
            "type": "int",
            "minOccurs": "1"
        },
        {
            "name": "androidorios",
            "type": "int",
            "minOccurs": "1"
        }
    ]
}

FEATURES = {
    "hourwise": ["getHourwiseAttendance"],
    "academics": ["getExamDetails", "getStudentExamProvisionalResult", "getStudentExamRevaluationResult",
                  "getSubjects", "getSubCategoryWiseStatus", "getSubCategorySemesterWiseStatus",
                  "getProgramSubCategoryWiseSubjects"],
    "fees": ["getFeeDetails", "getFinanceDetails"],
    "placement": ["getStudentAllOfferedJobs", "getStudentPlacementRequired", "getJobCriteria",
                  "getJobQuestions", "getResumeUploads", "getWillingnessRejectReasons",
                  "getPlacementRegistrationDetailsList", "getPlacementWillingnessRegistrationOpen"],
    "library": ["getLibraryTransaction"],
    "campus": ["getHostelDetails", "getTransportDetails", "getViewNotificationListJson"],
    # getStudentPhoto is deliberately ABSENT: it returns raw JPEG bytes, not a
    # JSON envelope, and it is fetched on demand via client.photo(numeric_id).
    # Listing it here made every sync try to json.loads() an image, raise
    # "response decrypt failed", and abort the whole batch as a transport
    # fault — profile never landed and 11 already-fetched ops were discarded.
    "profile": ["getPersonalDetails"],
    "attendance": ["getCummulativeAttendance", "getSubjectwiseAttendance"],
    "marks": ["getInternalMarkDetails"],
}

# opt-in slugs (see FEATURES above): enable with SCOPE_FEATURES=all or an
# explicit list, e.g. SCOPE_FEATURES=placement,library,campus
DEFAULT_FEATURES = "hourwise,academics,fees,profile,attendance,marks"


def enabled_features() -> set[str]:
    """Parse env SCOPE_FEATURES: comma slugs -> set; "all" -> every feature;
    "off"/"" -> empty set; unknown slugs logged once and ignored."""
    raw = os.environ.get("SCOPE_FEATURES", DEFAULT_FEATURES).strip()
    if raw in ("", "off"):
        return set()
    if raw == "all":
        return set(FEATURES)
    out = set()
    for slug in (s.strip() for s in raw.split(",")):
        if not slug:
            continue
        if slug in FEATURES:
            out.add(slug)
        else:
            log.warning("scope.features unknown slug=%r ignored (valid: %s)", slug, ",".join(FEATURES))
    return out


def ops_for(features: set[str]) -> list[str]:
    """Deduped op list for sync, in FEATURES order."""
    out: list[str] = []
    for feat, ops in FEATURES.items():
        if feat in features:
            for op in ops:
                if op not in out:
                    out.append(op)
    return out
