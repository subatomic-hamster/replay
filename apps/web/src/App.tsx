import { useEffect } from "react";
import { navigate, useLocation } from "./router";
import { Library } from "./screens/Library";
import { Watch } from "./screens/Watch";
import { Highlights } from "./screens/Highlights";
import { Review } from "./screens/Review";
import { Pair } from "./screens/Pair";
import { Companion } from "./screens/Companion";
import { Calibrate, UploadCreate, UploadFile, UploadStatus } from "./screens/Upload";

export function App() {
  const { pathname } = useLocation();
  const seg = pathname.split("/").filter(Boolean);

  useEffect(() => {
    if (seg.length === 0) navigate("/tv", true);
  }, [seg.length]);

  const tv = seg[0] === "tv";
  const isPhone = seg[0] === "upload" || seg[0] === "companion";

  return (
    <div
      className={`${isPhone ? "app phone-app" : "app tv-app"}${
        seg[2] === "calibrate" ? " wide-app" : ""
      }`}
    >
      {route(seg, tv)}
    </div>
  );
}

function route(seg: string[], tv: boolean) {
  if (tv) {
    if (seg.length === 1) return <Library />;
    if (seg[1] === "pair") return <Pair />;
    const id = seg[1];
    if (seg[2] === "highlights") return <Highlights key={id} gameId={id} />;
    if (seg[2] === "review") return <Review key={id} gameId={id} />;
    return <Watch key={id} gameId={id} />;
  }
  // H4: the phone companion, paired by the 4-digit code the TV shows.
  if (seg[0] === "companion") return <Companion key={seg[1]} code={seg[1]} />;
  if (seg[0] === "upload") {
    if (seg.length === 1) return <UploadCreate />;
    const id = seg[1];
    if (seg[2] === "calibrate") return <Calibrate key={id} gameId={id} />;
    if (seg[2] === "status") return <UploadStatus key={id} gameId={id} />;
    return <UploadFile key={id} gameId={id} />;
  }
  return <div className="screen">Loading…</div>;
}
