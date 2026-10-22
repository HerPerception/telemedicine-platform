# ENG-004: video consultation rooms, the waiting room and admission control

The visit loop had no consultation in it. This adds the room a booked
appointment is held in, the waiting room in front of it, and the admission
control that decides who gets in.

* telemedicine/video.py - VideoService. A room is bound to one appointment,
  and therefore to one patient and one clinician. The patient joins into the
  waiting room and the clinician admits them; the clinician joins directly
  and sees who is waiting. A patient never sees who else is in the room, and
  cannot admit themselves.
* The room is only available inside the appointment window, with a grace
  period either side. A join before the window is refused with a reason and
  a hint about when to try again; one after it is refused as final.
* The join token is signed with a secret that belongs to the room, so it
  cannot be used for another room or another participant, and it expires
  after five minutes.
* telemedicine/video_api.py - the HTTP surface under /video, with its own
  error shape: a client that cannot join is told why, whether trying again
  could work, and when to try.
* The media transport is a seam. The MVP has no provider - no signalling, no
  TURN, no vendor - so the implementation here is a loopback that makes the
  rules testable, and the adapter that would carry the stream is named in
  docs/video-design.md.

Amendments to earlier features, recorded in the design document and in the
coordination log: Action.JOIN and two rules for it, because taking part in
a consultation is neither reading a record nor changing one; get_appointment,
which returns an appointment without auditing it, for the window and the
participants; NotFoundError, so that a room which is not there is a 404; and
the server can now serve several applications under different path
prefixes, which is how the FHIR API and the video rooms sit on one port.

The traceability document now covers the three video criteria, and two more
that the feature added: the waiting room with clinician admission control,
and the join credential being bound to one room, one participant and a
short life. The check caught the two new criteria until they were added to
its list, which is the point of having it.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
