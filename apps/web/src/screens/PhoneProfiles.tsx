// M10 phone companion: player profiles. Touch, not D-pad: this page never runs on the TV.
// `/profiles` lists them and creates one; `/profiles/:id` edits name / sports / positions,
// uploads the profile photo, and holds the opt-in face enrollment: an explicit consent
// step (what is stored, how to delete it) gates the photo picker and the button, 1–10
// photos, and "Delete my face data" removes the embedding (D-58). Suggestions are never
// shown here; the TV shows them, and face ones only for an enrolled profile.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Avatar } from "../components/Avatar";
import { navigate } from "../router";
import { useAsync } from "../ui";
import {
  FACE_CONSENT,
  FACE_PHOTOS_MAX,
  facePhotosError,
  sportsText,
  type Profile,
} from "../../../../packages/tv-core/src/profiles";

const splitList = (v: string) =>
  v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

/** "Basketball · 2 games". The list route sends `sports: null` when they are derived from
 *  the links (no stats on the list), so the honest summary is the game count, from
 *  `linked`; "No games linked yet" only when there really are none. */
function profileMeta(p: Profile): string {
  const games = new Set((p.linked ?? []).map((l) => l.game_id)).size;
  const count = games
    ? `${games} ${games === 1 ? "game" : "games"}`
    : "No games linked yet";
  return p.sports?.length ? `${sportsText(p)} · ${count}` : count;
}

export function ProfilesPhone() {
  const { data, error, reload } = useAsync(() => api.listProfiles(), []);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");

  const create = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    api.createProfile({ name: name.trim() }).then(
      (p) => navigate(`/profiles/${p.profile_id}`),
      (err: Error) => setNote(`Not created: ${err.message}`),
    );
  };

  return (
    <div className="phone profiles-phone" data-testid="phone-profiles">
      <h1>Player profiles</h1>
      {error ? (
        <p className="error" data-testid="phone-profiles-error">
          Could not reach the Replay API: {error.message}{" "}
          <button type="button" className="secondary" onClick={reload}>
            Retry
          </button>
        </p>
      ) : null}
      <ul className="phone-hits">
        {(data ?? []).map((p) => (
          <li
            key={p.profile_id}
            data-testid="phone-profile"
            data-profile-id={p.profile_id}
          >
            {/* The whole row is the link: a real <a>, so Tab and Enter reach it too. */}
            <a
              className="profile-row"
              href={`/profiles/${p.profile_id}`}
              onClick={(e) => {
                e.preventDefault();
                navigate(`/profiles/${p.profile_id}`);
              }}
            >
              <Avatar name={p.name} photo={p.photo_url} size={48} />
              <span className="profile-row-text">
                <b>{p.name}</b>
                <span className="dim" data-testid="phone-profile-meta">
                  {profileMeta(p)}
                </span>
              </span>
            </a>
          </li>
        ))}
      </ul>
      {data && data.length === 0 ? (
        <p className="dim">No profiles yet.</p>
      ) : null}
      <form onSubmit={create}>
        <h2>New profile</h2>
        <label>
          Name
          <input
            data-testid="profile-name-input"
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Jordan"
          />
        </label>
        <button
          type="submit"
          data-testid="profile-create"
          disabled={!name.trim()}
        >
          Create profile
        </button>
        {note ? <p className="error">{note}</p> : null}
      </form>
    </div>
  );
}

export function ProfileEdit({ profileId }: { profileId: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState("");
  const { data: sports } = useAsync(() => api.listSports(), []);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [positions, setPositions] = useState("");
  const [note, setNote] = useState("");

  const adopt = useCallback((p: Profile) => {
    setProfile(p);
    setName(p.name);
    setPicked(p.user_edited_fields.includes("sports") ? (p.sports ?? []) : []);
    setPositions(p.positions.join(", "));
  }, []);

  useEffect(() => {
    api
      .getProfile(profileId)
      .then(adopt, (e: Error) => setLoadError(e.message));
  }, [profileId, adopt]);

  if (loadError)
    return (
      <div className="phone">
        <p className="error" data-testid="profile-load-error">
          {loadError}
        </p>
      </div>
    );
  if (!profile) return <div className="phone">Loading…</div>;

  const save = (e: FormEvent) => {
    e.preventDefault();
    api
      .patchProfile(profileId, {
        name: name.trim(),
        // none ticked: the sports come from the linked games again
        sports: picked.length ? picked : null,
        positions: splitList(positions),
      })
      .then(
        (p) => {
          adopt(p);
          setNote("Saved");
        },
        (err: Error) => setNote(`Not saved: ${err.message}`),
      );
  };

  const uploadPhoto = (file: File | undefined) => {
    if (!file) return;
    setNote("Uploading photo…");
    api.uploadProfilePhoto(profileId, file).then(
      (p) => {
        adopt(p);
        setNote("Photo saved");
      },
      (err: Error) => setNote(`Photo not saved: ${err.message}`),
    );
  };

  return (
    <div
      className="phone profile-edit"
      data-testid="profile-edit"
      data-profile-id={profileId}
    >
      <p>
        <a
          href="/profiles"
          onClick={(e) => {
            e.preventDefault();
            navigate("/profiles");
          }}
        >
          ← All profiles
        </a>
      </p>
      <div className="profile-phone-head">
        <Avatar name={profile.name} photo={profile.photo_url} size={96} />
        <h1 data-testid="profile-edit-name">{profile.name}</h1>
      </div>
      <p className="dim">
        Linked in {profile.linked.length}{" "}
        {profile.linked.length === 1 ? "game" : "games"} · link players from the
        TV
      </p>

      <form onSubmit={save}>
        <label>
          Name
          <input
            data-testid="profile-name-input"
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <fieldset data-testid="profile-sports">
          <legend>Sports (none ticked: taken from the linked games)</legend>
          {(sports ?? []).map((s) => (
            <label key={s.id} className="radio">
              <input
                type="checkbox"
                data-testid={`profile-sport-${s.id}`}
                checked={picked.includes(s.id)}
                onChange={(e) =>
                  setPicked((cur) =>
                    e.target.checked
                      ? [...cur, s.id]
                      : cur.filter((x) => x !== s.id),
                  )
                }
              />
              {s.display_name}
            </label>
          ))}
        </fieldset>
        <label>
          Positions (comma separated)
          <input
            data-testid="profile-positions-input"
            value={positions}
            onChange={(e) => setPositions(e.target.value)}
          />
        </label>
        <button
          type="submit"
          data-testid="profile-save"
          disabled={!name.trim()}
        >
          Save profile
        </button>
      </form>

      <h2>Profile photo</h2>
      <p className="dim">
        Shown on the TV and the player card. Re-encoded on the server, so no
        location data is kept.
      </p>
      <input
        type="file"
        accept="image/*"
        data-testid="profile-photo-input"
        onChange={(e) => uploadPhoto(e.target.files?.[0])}
      />

      {note ? (
        <p
          data-testid="profile-note"
          className={/^(Not|Photo not)/.test(note) ? "error" : "dim"}
        >
          {note}
        </p>
      ) : null}

      <FaceEnrollment profile={profile} onChange={adopt} />
    </div>
  );
}

/** Opt-in face matching. Nothing here works until the consent box is ticked. */
function FaceEnrollment({
  profile,
  onChange,
}: {
  profile: Profile;
  onChange: (p: Profile) => void;
}) {
  const [consent, setConsent] = useState(false);
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const countError = photos.length ? facePhotosError(photos.length) : null;
  const ready = consent && !busy && photos.length > 0 && !countError;

  const enroll = () => {
    if (!consent) return; // never without the person's explicit yes
    const err = facePhotosError(photos.length);
    if (err) return setNote(err);
    setBusy(true);
    setNote("Enrolling…");
    api
      .enrollFace(profile.profile_id, photos, true)
      .then(
        (p) => {
          onChange(p);
          setPhotos([]);
          setConsent(false);
          setNote(
            "Enrolled. Your photos were deleted; one face embedding is stored.",
          );
        },
        (e: Error) => setNote(`Not enrolled: ${e.message}`),
      )
      .finally(() => setBusy(false));
  };

  const forget = () => {
    setBusy(true);
    api
      .deleteFace(profile.profile_id)
      .then(
        (p) => {
          onChange(p);
          setNote("Your face data was deleted.");
        },
        (e: Error) => setNote(`Not deleted: ${e.message}`),
      )
      .finally(() => setBusy(false));
  };

  return (
    <section
      className="face"
      data-testid="face-section"
      data-enrolled={profile.face_enrolled ? "true" : "false"}
    >
      <h2>Face matching (optional)</h2>
      {profile.face_enrolled ? (
        <>
          <p data-testid="face-status">
            Enrolled: one face embedding is stored for this profile, used only
            to suggest links you confirm.
          </p>
          <button
            type="button"
            className="secondary"
            data-testid="face-delete"
            disabled={busy}
            onClick={forget}
          >
            Delete my face data
          </button>
        </>
      ) : (
        <fieldset data-testid="face-consent-step">
          <legend>Before you enroll</legend>
          <ul className="consent-text" data-testid="face-consent-text">
            {FACE_CONSENT.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <label className="radio">
            <input
              type="checkbox"
              data-testid="face-consent"
              checked={consent}
              onChange={(e) => {
                setConsent(e.target.checked);
                if (!e.target.checked) setPhotos([]);
              }}
            />
            I am this player (or their parent or guardian) and I agree to face
            matching as described above.
          </label>
          <label>
            1 to {FACE_PHOTOS_MAX} clear photos of your face
            <input
              key={consent ? "consented" : "no-consent"} // unticking also empties the picker
              type="file"
              accept="image/*"
              multiple
              data-testid="face-photos"
              disabled={!consent}
              onChange={(e) => setPhotos([...(e.target.files ?? [])])}
            />
          </label>
          {photos.length ? (
            <p
              className={countError ? "error" : "dim"}
              data-testid="face-photo-count"
            >
              {countError ??
                `${photos.length} photo${photos.length === 1 ? "" : "s"} picked`}
            </p>
          ) : null}
          <button
            type="button"
            data-testid="face-enroll"
            disabled={!ready}
            onClick={enroll}
          >
            Enroll my face
          </button>
        </fieldset>
      )}
      {note ? (
        <p
          data-testid="face-note"
          className={/^Not /.test(note) ? "error" : "dim"}
        >
          {note}
        </p>
      ) : null}
    </section>
  );
}
