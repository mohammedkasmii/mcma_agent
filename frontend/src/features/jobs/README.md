# jobs

Reserved for automation job state: job list, active-job recovery after a
reload, and the centralised mapping from backend job states to the labels
shown to an employee.

Empty in STEP 1. Job state is read from the backend, never held only in a
frontend variable, and progress is shown as named milestones rather than a
fabricated percentage.

This file exists so the directory is tracked by git, which does not record
empty directories.
