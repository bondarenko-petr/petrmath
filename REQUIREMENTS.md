# Tutor Management System --- Requirements

**Version:** 1.0\
**Status:** MVP specification\
**UI language:** Russian\
**Currency:** RUB (₽)

## 1. Project Goal

Build a responsive web application for an individual online mathematics
tutor.

The system combines: - student management; - lesson scheduling and
recurring lessons; - teacher Google Calendar synchronization; - lesson
materials; - homework assignment, submission, review, and revisions; -
lesson pricing and payment tracking; - a personal student dashboard.

The MVP is designed for one teacher and multiple students. The
architecture must allow a future integrated interactive whiteboard.

## 2. Roles

### Administrator / Teacher

The administrator can: - create and edit students; - create student
credentials and reset passwords; - set an individual default lesson
price and duration; - create, reschedule, cancel, and delete lessons; -
create recurring lesson series; - mark lessons as completed; - upload
lesson materials; - create and review homework; - request homework
revision; - record payments and prepayments; - view financial
statistics; - synchronize lessons to the teacher's Google Calendar.

### Student

A student can access only their own data and can: - view the next
lesson, current-week lessons, upcoming and previous lessons; - download
lesson materials; - view homework; - upload homework solutions and
revisions; - view teacher feedback; - view their own payment status and
payment history.

A student cannot create, reschedule, cancel, delete, or edit lessons.

## 3. Authentication and Account Management

There is no public registration.

### Administrator account

-   Created during initial deployment/setup.
-   Initial credentials must never be hard-coded.
-   Initial secrets are supplied through secure
    environment/configuration or a dedicated initialization procedure.
-   Administrator can change the password.
-   Plain-text passwords must never be stored in the database, logs, or
    Git.

### Student accounts

-   Created only by the administrator.
-   Administrator defines name, unique username, default lesson price,
    and default lesson duration.
-   The system generates a cryptographically secure temporary password.
-   The administrator manually gives the username and temporary password
    to the student.
-   At first login, the student must choose a new password before
    receiving normal access.
-   The same procedure applies after an administrator password reset.
-   Email-based password recovery is not required in the MVP.

### Username rules

-   Usernames are unique and compared case-insensitively.
-   The system may suggest a username based on the student's name.
-   Administrator may edit it before account creation.

### Security

-   Use Argon2id or an equivalent secure password-hashing mechanism.
-   Use HTTPS in production.
-   Rate-limit failed login attempts.
-   Enforce server-side authorization on all protected resources.
-   Use secure session management and secure cookie settings when cookie
    sessions are used.

Conceptual model:

    User
    ├── id
    ├── username
    ├── password_hash
    ├── role: ADMIN | STUDENT
    ├── must_change_password
    ├── is_active
    ├── created_at
    └── password_changed_at

Student-specific information belongs in `StudentProfile`.

## 4. Student Management

Administrator can create/edit students, change usernames, reset
passwords, set default price/duration, archive/deactivate students, and
view their lessons, homework, materials, and payments.

Students with historical lessons/payments should normally be archived
instead of physically deleted.

Parent/family accounts are outside the MVP.

## 5. Lesson Format

All lessons are online.

Integrated video conferencing and an interactive whiteboard are outside
the MVP.

Lesson duration is an arbitrary number of minutes. A student has a
default duration (e.g. 45 minutes), but it can be overridden for an
individual lesson.

The architecture must allow a future `WhiteboardSession` associated with
a `Lesson`.

## 6. Lessons and Scheduling

A lesson contains: - student; - date/start time; - duration; - price; -
optional topic; - status.

Default price and duration are copied from the student profile but may
be overridden.

The lesson stores its own price snapshot. Changing a student's default
price must not modify existing/historical lesson prices.

## 7. Recurring Lessons

Administrator can create a series using: - one or more weekdays; -
time; - duration; - recurrence end date.

When changing/deleting a recurring occurrence, support: - only this
lesson; - this and following lessons; - entire series.

## 8. Lesson Statuses

MVP: - `scheduled` - `completed` - `cancelled`

Cancelled lessons remain in history. Erroneous future entries may be
deleted.

No-show/late-arrival policy is deferred.

## 9. Google Calendar

The application database is the scheduling source of truth.

MVP synchronization is one-way:

    Web application → Teacher Google Calendar

Creating, rescheduling, changing, or cancelling a lesson updates the
corresponding Google Calendar event.

Bidirectional synchronization is outside the MVP.

## 10. Administrator Dashboard

Main sections: - Dashboard; - Schedule; - Students; - Homework; -
Finances; - Settings.

Dashboard should show: - today's lessons; - current-week schedule; -
upcoming lessons; - homework awaiting review; - unpaid lessons; -
current-month financial summary.

Administrator needs a calendar view containing all students.

## 11. Student Dashboard

The student does not need a full calendar UI.

Dashboard emphasizes: - next lesson; - current-week lessons; - next
several lessons; - open/overdue/submitted/reviewed homework; - latest
lesson materials; - payment state.

A separate page provides complete lesson/history information.

## 12. Lesson Materials and Files

Teacher can attach: - topic; - text notes; - lesson summary; -
supplementary materials; - multiple files.

Allowed MVP file formats: - PDF - JPG/JPEG - PNG - DOCX

Maximum size: **5 MB per file**.

File size and type must be validated server-side.

## 13. Homework

Homework belongs to a specific lesson.

A later lesson does not replace or close homework from an earlier
lesson.

Homework can contain: - description/text; - teacher attachments; -
optional due date; - teacher comment.

A student opens a specific homework item and uploads the solution there;
the student does not manually choose the lesson during upload.

## 14. Homework Workflow

Statuses: - `assigned` - `submitted` - `revision` - `reviewed`

Teacher has an "Awaiting review" queue.

Teacher can: - inspect files; - comment; - accept/review; - return for
revision.

Revisions create new submission versions. Old versions are preserved
with timestamps, files, and feedback.

## 15. Pricing

Currency is **RUB (₽)** only.

Each student has a default lesson price. It is copied to each created
lesson and becomes that lesson's own price.

Money must not use floating-point arithmetic. Store values using an
exact monetary representation (e.g. integer kopecks).

## 16. Payments and Prepayments

Payments are separate from lessons.

A payment stores: - student; - amount; - payment date; - optional
comment.

A payment may cover one or multiple lessons.

Prepayments are supported. Unallocated money remains available as
student credit and can later be allocated to completed lessons.

Core financial model:

    Lesson
    Payment
    PaymentAllocation

Do not model finance solely with `paid=true/false`.

## 17. Student Payment Display

Use human-readable states, for example: - `✓ Всё оплачено` -
`К оплате: 3 000 ₽` - `Предоплата: 4 500 ₽`

Student can view their own payment/lesson history.

## 18. Administrator Finances

Administrator can view: - payments received for a period; - completed
lesson count; - value of completed lessons; - unpaid amount; - unpaid
lessons grouped by student.

Administrator can record a payment for one or multiple lessons.

## 19. Notifications

Not included in MVP: - email reminders; - SMS; - WhatsApp automation; -
Telegram; - push notifications.

## 20. Future Interactive Whiteboard

Not part of MVP.

Architecture should permit a future:

    WhiteboardSession → Lesson

Possible future capabilities include collaborative drawing, formulas,
geometry, images, saved board state, and lesson history.

## 21. Preliminary Domain Entities

    User
    StudentProfile
    LessonSeries
    Lesson
    LessonAttachment
    Homework
    HomeworkAttachment
    HomeworkSubmission
    SubmissionAttachment
    Payment
    PaymentAllocation
    GoogleCalendarIntegration

Future:

    WhiteboardSession

## 22. MVP Scope

Included: - administrator/student authentication; - administrator
initialization; - admin-created student accounts; - temporary passwords
and forced password change; - administrator password reset for
students; - student management; - individual prices and durations; -
scheduling and recurring lessons; - rescheduling/cancellation; - teacher
Google Calendar synchronization; - student dashboard; - lesson
materials; - file uploads up to 5 MB; - homework submissions, review,
revisions, and version history; - payments and prepayments; - financial
overview; - responsive desktop/tablet/mobile web UI.

Not included: - public registration; - parent accounts; - email password
recovery; - integrated video conferencing; - interactive whiteboard; -
automated notifications; - bidirectional Google Calendar
synchronization; - full accounting/invoicing; - native mobile
application.
