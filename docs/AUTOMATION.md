# CRM automation: local simulation release

Open **Automations** (`/automation`) to configure rules and review sequences. **My work today** (`/my-work`) opens the callback/task queue. Managers can select **Team queue** to see branch work, including unassigned callbacks and overdue items. Existing assignment reminders and manually planned follow-ups remain under **Follow-ups**, linked from the new queue.

## Implemented

- Disabled-by-default rules scoped to a branch and source (website, call, WhatsApp, manual or all). Only managers configure rules or enroll historic records. Counsellors view and complete their own work; managers see their authorized branches.
- Automatic enrollment of eligible records received after the rule was enabled. Source-specific rules take priority over the all-source rule. Each target enrolls once; separate opportunities are not merged by phone number.
- Configurable initial acknowledgement, callback deadline and up to 12 message/task steps within 30 days. Delays are in minutes from enrollment. The starter sequence suggests day 1 calling, day 2 course information, day 3 interest check and day 7 review.
- Incoming missed calls without an enquiry create callback tasks only. New website leads and inbound WhatsApp conversations support sequences. Raw website submissions awaiting identity review are not enrolled until they produce a lead. Answered/outgoing calls do not automatically enroll as missed calls.
- Lead work follows the current active owner. Raw call/conversation work uses eligible branch counsellors and retains an eligible assignee. If nobody is eligible it enters the manager queue. This does not change canonical contact ownership or lead routing.
- Optional Monday–Saturday business hours in IST. Quiet hours defer message simulations and task deadlines. At most two message simulations per phone/contact **per branch per day**; extra steps move to the next business day.
- Rule snapshots/version numbers preserve a running sequence when a rule is edited. Disabling a rule pauses existing runs. Enabling it again requires explicit manager resumption of paused runs.
- New customer replies and manual staff replies pause the sequence and create a human handoff task. Opt-outs, closed leads, enquiries marked as requiring no further follow-up, converted missed calls and branch transfers stop the sequence and cancel pending work. Inactive channels also stop conversation runs. These checks occur when the worker polls; the default Celery interval is 30 seconds.
- Reason-required pause/stop controls for lead owners/managers; manager-only resume shifts pending deadlines by the paused duration and restores cancelled step tasks. Completed actions never repeat. Managers should review the reply before resuming a handoff.
- Overdue tasks escalate once to the manager dashboard queue. Completion requires a recorded outcome. The audit trail records enrollment, simulations, task creation/completion, reassignment, pause/stop/resume and escalation. Runs finish after scheduled steps and open tasks are complete.
- Authenticated, branch-scoped REST endpoints under `/api/v1/automation/{rules,runs,work,audit}/`. Fields that should be system-controlled cannot be supplied by clients. APIs never return provider secrets.

## LearnMore starter rules and course guide

The Rules tab includes a LearnMore starter library. Managers select **Install starter rules**, choose an active authorized branch, and optionally select **Enable rules for new enquiries**. Unchecked installations remain drafts. Repeating installation preserves existing rule text and steps. An already-active custom rule for the same source is kept; the conflicting starter remains disabled and the result identifies that source. Enabled source-specific rules take priority over the general rule. Installing or enabling does not enroll historical records or resume paused sequences.

| Rule | Automated work |
| --- | --- |
| General IT course enquiry | Ten-minute initial contact task; course-list acknowledgement preview; qualification after 30 minutes; course guide on day 1; syllabus/batch discussion on day 2; demo coordination on day 3; decision review on day 7. |
| Website enquiry | Five-minute contact deadline, course guidance, demo offer and seven-day review. |
| Incoming missed call | Five-minute callback task only; no message sequence for raw missed calls. |
| WhatsApp enquiry | Ten-minute contact deadline, counselling and interest follow-up. Replies pause automation for human review. |
| Walk-in/manual enquiry | Thirty-minute contact deadline, course-fit discussion, demo offer and seven-day decision review. |

Message actions are audit previews, while task actions create real CRM work. Demo coordination asks staff to confirm candidate interest and trainer availability; it does not book a demo automatically. Business hours default to Monday–Saturday, 9 am–6 pm IST. The worker must be running for enrollment and scheduled work.

The course guide includes Python and Java full stack, .NET full stack, Data Science, Data Analytics, AI, Machine Learning, AWS, Azure, DevOps, Software Testing, Selenium, Power BI, SQL and Advanced Excel, using names from the existing CRM catalogue. Staff can copy the guide and search the complete existing course catalogue on the page. Branch staff must confirm batch availability, syllabus and approved fees; templates make no fee or placement guarantees.

API additions: `GET /api/v1/automation/rules/templates/` returns template previews and featured courses to sales users; manager-only `POST /api/v1/automation/rules/install-starters/` accepts `{ "branch": "<branch UUID>", "enable": false }` and reports created/enabled/preserved rules and source conflicts. Installation is transactional and locks the branch to coordinate with rule editing.

The command uses the same installation service:

```powershell
# Install drafts in accessible active branches.
.\.venv\Scripts\python.exe backend\manage.py seed_learnmore_rules --actor <manager-username>
# Enable only the general course rule in one branch for new arrivals.
.\.venv\Scripts\python.exe backend\manage.py seed_learnmore_rules --actor <manager-username> --branch marathahalli --source all --enable
```

## Message safety and current limits

**This release never sends messages.** A message action creates an audit preview labelled `SIMULATION ONLY — NOT SENT`. It does not create WhatsApp outbox rows, invoke a transport, mark a lead contacted or acknowledge assignment. This remains true even if the separate inbox is configured for live sending. No real calls, external emails or push notifications are triggered; manager alerts are durable CRM tasks.

The module uses deterministic rules. Structured student qualification and internal demo booking/attendance are now provided by the [education workflows](EDTECH_WORKFLOWS.md). AI qualification/scoring, automatic conversational replies, external calendar booking, fee/payment workflows and indefinite re-engagement campaigns remain future work. The production Meta template/consent/customer-service-window checks remain in the existing messaging service; a future live automation adapter must use them, with explicit approval before sending.

Automatic intake can only act on data that reaches this CRM. Public hosting and website deployment, the private second website and MyOperator API ingestion remain separate setup work. Polling does not import external call logs by itself.

## Running

Apply migrations before starting workers:

```powershell
.\.venv\Scripts\python.exe backend\manage.py migrate
```

Production uses the existing Celery worker and a **single** beat scheduler. The `automation.process` task is registered in the 30-second beat schedule. For local development without Redis, run either a single pass or one polling process:

```powershell
.\.venv\Scripts\python.exe backend\manage.py process_automations
.\.venv\Scripts\python.exe backend\manage.py process_automations --watch
```

Use one local poller or the Celery scheduler, rather than both. PostgreSQL row locks plus target/step uniqueness protect duplicate enrollment and task execution across overlapping workers. SQLite is a local preview only; production concurrency checks use isolated PostgreSQL.

## Test it

1. Sign in with an existing manager account. Create a rule for an authorized branch, leave simulation text visible, and enable it. For quick testing set acknowledgement delay to zero and disable business hours.
2. Create a new enquiry in that branch, record an incoming missed call, or process a mocked signed inbound WhatsApp webhook. Existing records can be selected using **Enroll existing enquiry**.
3. Allow one worker cycle, then inspect **Sequences**, **My work today / Team queue** and **Audit trail**. Complete the callback with an outcome. No provider send should appear.
4. Test a customer reply, opt-out, lead closure and manual pause/resume. Pending work should pause or cancel as described above.

No rules or sample customer records are inserted automatically during installation.

## Verification (26 October 2026)

The full isolated PostgreSQL regression suite passed **174 tests, zero skips**, including four workers simultaneously enrolling and processing one target with one resulting run, callback and simulated acknowledgement. A subsequent focused SQLite run passed 18 automation tests, with its PostgreSQL-only concurrency test skipped, including an additional blank-acknowledgement API test. All **32 frontend tests** passed. TypeScript, ESLint, production build, migration consistency and warning-free OpenAPI validation passed.

The local SQLite database was backed up before applying `automation.0001_initial`. The backend and website preview were restarted together using matching runtime-only intake secrets, mock WhatsApp and disabled SMTP. The automation poller runs locally every ten seconds. No default rule, sample enquiry, privileged user or real outbound message was created. Existing sessions may require signing in again after the local backend restart.
