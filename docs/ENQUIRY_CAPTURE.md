# Unified enquiry capture

Use **New enquiry** from Contacts or Lead pipeline to capture a new candidate and their enquiry in one form. The form includes name, mobile/email, primary course, additional course interests, training mode, candidate city, preferred training branch, assigned branch, source and next follow-up. At least one of mobile/email is required. Saving creates the contact, enquiry and qualification in one transaction using existing identity matching and counsellor routing.

For an existing candidate, choose **New enquiry** from their contact page. Contact details are displayed in the form. Changes to shared contact identity continue through the contact page's existing name and phone/email workflows; creating or editing an enquiry does not replace shared identifiers. Possible duplicates enter manager review without creating a new contact or enquiry. The entered form details remain available using **Review entered details**.

## Course interests and training preferences

- Select up to 20 course interests, including custom course names. **Course name** is the primary course for counselling. Add secondary courses using **Additional course interest → Add course**. Course names containing commas remain one catalogue entry.
- Selected interests appear as tags. **Make primary** changes the counselling course while retaining the other interests. Removing the primary selects the first remaining interest; removing all interests requires a primary course before saving.
- The primary course is stored as `Qualification.course_interest` and kept consistent with `Lead.title`. Other interests are stored in `Qualification.course_interests`. APIs reject duplicate names and a primary course outside the selected list.
- **Candidate city** records the city where the candidate lives. It is independent of the **Preferred training branch**. The existing free-text preferred location/area is preserved for legacy counselling notes.
- Preferred branch options expose only active branch IDs and names to sales staff. Preference selection grants no cross-branch record access and does not transfer an enquiry or change its assigned counsellor. The **Assigned branch** still controls routing and access.
- Training modes remain Undecided, Online, Classroom and Hybrid. Demo bookings, attendance and counsellor reassignment keep their existing audited workflows.

The Edit enquiry and Student qualification forms use the same course and preference controls. Enquiry reads include qualification details only for users allowed to edit the enquiry, preserving owner/manager access to counselling information.

## Migration and compatibility

Apply `education.0002_enquiry_preferences` before starting the updated backend and workers. It adds city, course interests and preferred branch. Existing qualification records retain their data; their existing course (or enquiry title when blank) becomes the initial interest. Location text is not guessed into a city or branch. Old enquiries without a qualification remain readable, and legacy lead creation endpoints continue to work.

```bash
python3 backend/manage.py migrate --settings=config.production_settings
cd frontend
npm ci
npm run build
```

These commands use the Ubuntu production settings and PostgreSQL database. Local development uses the default settings instead. Restart the application services after deployment. No outbound message or demo booking is triggered by saving the form.

## API

- `POST /api/v1/leads/intake/`: send either `candidate: {full_name, mobile, email}` or an existing `contact` ID, plus normal enquiry fields and optional nested `qualification`. Success returns the enquiry; duplicate identity returns HTTP 409 and the existing duplicate-review representation. Any validation or routing failure rolls back new contact/enquiry writes.
- Existing `POST /api/v1/leads/` and `PATCH /api/v1/leads/<id>/` accept nested qualification data so enquiries and their learning preferences save together. Qualification-only updates remain available on the existing education endpoint.
- `GET /api/v1/education/preferred-branches/`: active branch IDs and names only, available to authorized sales users.
- The qualification API accepts `course_interests`, `city`, `preferred_branch` and existing qualification fields. Its response includes `preferred_branch_name`.
