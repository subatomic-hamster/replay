// A profile's photo in a circle, or its initials when it has none.
import { api } from "../api/client";
import { initials } from "../../../../packages/tv-core/src/profiles";

export function Avatar({ name, photo, size }: { name: string; photo: string | null; size: number }) {
  return (
    <span
      className="avatar"
      data-testid="avatar"
      data-photo={photo ? "true" : "false"}
      style={{ width: size, height: size, fontSize: Math.max(24, size * 0.38) }}
    >
      {photo ? <img src={api.profileMediaUrl(photo)} alt="" /> : initials(name)}
    </span>
  );
}
