# Assign a course to a student

Counsellors can select a course when creating or editing a student enquiry. Open Contacts, choose the student, and create an enquiry; for an existing enquiry, open Lead pipeline, choose the record, and select Edit enquiry. Search in Course name, choose a suggestion and save. Course selection does not change the counsellor assignment.

The same suggestions are available when creating an enquiry from a call, creating a WhatsApp course enquiry, updating Course interest in student qualification, and booking a Demo course. Existing authorization still controls who can create or edit each record. WhatsApp enquiry linking remains a manager action.

The catalog contains 318 distinct suggestions from the supplied list. Repeated names are removed using whitespace-normalized, case-insensitive comparison. Course names and combinations otherwise retain their supplied wording; similar aliases and abbreviations are not automatically merged. The heading and non-course labels All, Contact Us, No Response, Not Mentioned, Other, Select Program and She Is Hr are excluded from suggestions. A custom course can still be typed when needed.

The course name on an enquiry is saved as its existing title, so the pipeline, student record, assignment history labels and WhatsApp ownership display continue to use it without a database migration. Qualification course interest and demo course remain separately editable fields. Existing records are not renamed by this update.

The shared list lives in `frontend/src/lib/course-catalog.json`. Add or revise suggestions there and rebuild the frontend. No Meta setup or external messaging is triggered by selecting a course.

## Apply the update on Ubuntu

Build during a quiet period on the small server. Stopping the frontend first reduces memory use; the website is unavailable during the build. Keep PostgreSQL and background services running. Run each command separately and stop on errors.

```bash
cd ~/apps/centralcrm-test
git pull --ff-only origin main
sudo systemctl stop centralcrm-frontend
export PATH="$HOME/.local/bin:$PATH"
export DJANGO_API_ORIGIN=http://127.0.0.1:8100
cd frontend
npm run build
sudo systemctl start centralcrm-frontend
sudo systemctl --no-pager status centralcrm-frontend
```

Then refresh the browser and open a student enquiry. If a build fails, share the error before attempting a restart; Next.js may have replaced the previous build output.
