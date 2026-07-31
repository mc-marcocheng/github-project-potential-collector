# Prospective Collection Protocol v1

Status: frozen for the first production cohort.

## 1. Population

The discovery population consists of first usable repository launch events
observed through GH Archive.

A valid discovery event must satisfy:

- `type == "CreateEvent"`
- `repo.id` is a valid integer
- `created_at` is available
- One of:
  - `payload.ref_type == "repository"`, or
  - `payload.ref_type == "branch"` and
    `payload.ref == payload.master_branch`

Current GH Archive data may not contain repository-level creation events.
Creation of the initial/default branch is therefore used as the operational
first usable public launch event.

This proxy may include a small number of recreated default branches and may
miss repositories that never create a usable branch. Repository API
`created_at`, snapshot state, and content availability are retained for
auditing.

All deterministically selected candidates are retained. Eligibility is derived
at snapshot time rather than applied destructively during discovery.

## 2. Deterministic sampling

Each repository is assigned a secret-keyed HMAC value based on its stable
GitHub repository ID.

A repository is selected when:

    HMAC_SAMPLE_VALUE(repository_id) < sampling_probability

The sampling probability is runtime configuration and may be changed for
future, unprocessed GH Archive hours. The effective inclusion probability
is stored with every selection record.

The collector does not enforce equality with probabilities used by earlier
runs. Downstream estimators must use each record's stored inclusion
probability when sampling weights are required.

The HMAC sampling key should normally remain unchanged. With the same key,
a sample selected at a lower probability is nested within a sample selected
at a higher probability.

## 3. Prediction landmark

Let `t_launch` be the accepted GH Archive repository-level creation event
or initial/default-branch creation event.

The prediction landmark is the 24-hour readiness point:

    t0 = t_launch + 24 hours

The purpose of the delay is to measure project content after the owner
has had one day to establish a launch-ready description and README.

The intended and actual snapshot timestamps are stored. The collector
must not capture a snapshot before t0.

A healthy hourly collection run will normally capture the snapshot
within approximately two hours after t0. Snapshot quality is classified
using the delay from t0.

The GitHub API repository `created_at` timestamp is retained for
auditing. It is not assumed to be identical to the accepted public
launch-event timestamp.

## 4. Snapshot content

At t0, the collector requests:

1. Repository metadata using the stable repository ID.
2. The current default-branch commit SHA.
3. The README at that exact commit SHA.
4. Training-only owner metadata.

The README is limited to 65,536 bytes by default. Invalid UTF-8 is replaced.
NUL bytes are removed. Content is not rendered, followed, imported, or
executed.

Interaction metrics are retained only for labels and auditing. They are not
public content-model inputs.

## 5. Eligibility v1

A snapshot is eligible when all of the following hold:

- The repository is public.
- It is not a fork.
- It is not archived or disabled.
- It is not marked as a mirror.
- A readiness-snapshot commit SHA exists.
- It contains sufficient meaningful project text:
  - README length of at least 200 normalized characters, or
  - Description length of at least 80 normalized characters.
- It is not an obvious personal configuration or generated
  dependency-cache repository.
- It is not obvious coursework, homework, or a collection of
  class assignments.
- Its qualifying text is not solely a recognized generated
  README template.

The exclusion rules are deterministic and implemented in
`collector/eligibility.py`.

Ineligible and inaccessible records remain in the selected cohort.

## 6. Observation schedule

For every selected repository, tasks are scheduled for:

- t0
- t0 + 30 days
- t0 + 90 days
- t0 + 180 days

Because t0 is 24 hours after the accepted launch event, the 180-day
outcome endpoint is 181 days after that event.

Outcome observations use:

    GET /repositories/{repository_id}

The intended endpoint, actual observation timestamp, and observation
delay are retained.

## 7. Primary outcome

For repositories observable 180 days after the readiness landmark:

    Y_180_10 = 1[stargazers_count(t0 + 180 days) >= 10]

This is an endpoint star-count target measured 180 days after the
24-hour readiness snapshot. It is not a target measured 180 days
after repository creation.

The snapshot star count is retained for auditing and secondary
analysis but is never supplied to the public content model.

## 8. Censoring

A repository returning 404, 410, or 451 at a horizon is recorded as
inaccessible.

For the primary scientific outcome, inaccessible repositories are censored
rather than assigned zero stars.

A separate public-survival-and-popularity composite may later count
inaccessible repositories as failures.

## 9. Timeliness

Snapshot and observation delay are measured from the exact intended
timestamp. Negative delays are invalid.

Quality is classified as:

- on_time: 0 <= delay <= 6 hours
- moderately_late: 6 hours < delay <= 24 hours
- late: delay > 24 hours

The highest-quality prospective evaluation may be restricted to on-time
records.

## 10. Owner metadata

Owner metadata is collected for nuisance adjustment and subgroup evaluation.
It is not supplied to the public content model.

Collected fields include:

- Account type
- Account creation date
- Follower count
- Following count
- Public repository count
- Public gist count

Owner grouping uses an HMAC-derived key. Raw owner IDs remain private.

## 11. Retry and terminal classifications

Terminal successful outcomes:

- HTTP 200
- HTTP 404, 410, or 451 when repository accessibility is being measured

Retryable failures include:

- Rate limits
- HTTP 429
- HTTP 5xx
- Timeouts
- Network failures
- Invalid API responses
- Unexpected API statuses

Temporary failures are never converted into labels.

## 12. Identity and publication

Repository names, owner IDs, README content, and descriptions are private
collection data.

Only aggregate operational reports may be published while outcomes mature.

Identity scrubbing is a separate, versioned modeling transformation and does
not modify the immutable raw snapshot records.

## 13. Protocol changes

Any substantive change requires a new protocol version. Existing records are
not rewritten to imitate a newer protocol.
