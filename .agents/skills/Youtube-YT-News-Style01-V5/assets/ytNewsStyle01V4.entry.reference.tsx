// YT-News Style 01 V4: the Remotion entry point of this one composition.
//
// Why it exists: the V4 gate (qc_layout), the render (render_episode) and the stills tool bundle from THIS file, not from
// index.tsx / Root.tsx. Root.tsx registers every pipeline of the repository and is edited by other pipelines on every run;
// V4 must not render differently (or fail to bundle) because of those edits. This entry imports only the V4 engine and the
// two sample JSON files that are its default props. Do not add other imports here: gate_integrity.mjs checks the import
// closure and refuses anything that is not V4-owned.
//
// Remotion Studio for V4:  cd remotion-composer && npx remotion studio src/ytNewsStyle01V4.entry.tsx
//
// A copy of this file is kept at <skill>/assets/ytNewsStyle01V4.entry.reference.tsx (must stay byte-identical).
import { Composition, registerRoot } from "remotion";
import { YtNewsStyle01V4, calculateYtNewsStyle01V4Metadata } from "./YtNewsStyle01V4";
import ytNewsStyle01V4Sample from "./ytNewsStyle01V4Sample.json";
import ytNewsStyle01V4SampleCaptions from "./ytNewsStyle01V4SampleCaptions.json";

const YtNewsStyle01V4Root: React.FC = () => (
  <Composition id="YtNewsStyle01V4" component={YtNewsStyle01V4} width={1920} height={1080} fps={25} defaultProps={{ episode: ytNewsStyle01V4Sample, captions: ytNewsStyle01V4SampleCaptions } as never} calculateMetadata={calculateYtNewsStyle01V4Metadata} />
);

registerRoot(YtNewsStyle01V4Root);
