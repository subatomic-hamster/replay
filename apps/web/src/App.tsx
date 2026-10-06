import { useEffect } from "react";
import { navigate, useLocation } from "./router";
import { Library } from "./screens/Library";
import { Watch } from "./screens/Watch";
import { Highlights } from "./screens/Highlights";
import { Review } from "./screens/Review";
import { Pair } from "./screens/Pair";
import { Replay, ReplayList } from "./screens/Replay";
import { Companion } from "./screens/Companion";
import { Clips } from "./screens/Clips";
import { Rallies } from "./screens/Rallies";
import { Search } from "./screens/Search";
import { Advice } from "./screens/Advice";
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
    // M13: clips + trim + 9:16 share, rallies + condensed game, search, advice.
    if (seg[2] === "clips") return <Clips key={id} gameId={id} />;
    if (seg[2] === "rallies") return <Rallies key={id} gameId={id} />;
    if (seg[2] === "search") return <Search key={id} gameId={id} />;
    if (seg[2] === "advice") return <Advice key={id} gameId={id} />;
    // M8: /tv/:id/replays (list) and /tv/:id/replays/:playId (angle view).
    if (seg[2] === "replays") {
      return seg[3] ? (
        <Replay key={`${id}/${seg[3]}`} gameId={id} playId={decodeURIComponent(seg[3])} />
      ) : (
        <ReplayList key={id} gameId={id} />
      );
    }
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
