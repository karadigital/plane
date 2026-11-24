/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { Font } from "@react-pdf/renderer";
import interBold from "@/app/assets/fonts/inter/bold.ttf?url";
import interHeavy from "@/app/assets/fonts/inter/heavy.ttf?url";
import interLight from "@/app/assets/fonts/inter/light.ttf?url";
import interMedium from "@/app/assets/fonts/inter/medium.ttf?url";
import interRegular from "@/app/assets/fonts/inter/regular.ttf?url";
import interSemibold from "@/app/assets/fonts/inter/semibold.ttf?url";
import interThin from "@/app/assets/fonts/inter/thin.ttf?url";
import interUltraBold from "@/app/assets/fonts/inter/ultrabold.ttf?url";
import interUltraLight from "@/app/assets/fonts/inter/ultralight.ttf?url";

export const PDF_FONT_FAMILY = "Inter";

Font.register({
  family: PDF_FONT_FAMILY,
  fonts: [
    { src: interThin, fontWeight: "thin" },
    { src: interThin, fontWeight: "thin", fontStyle: "italic" },
    { src: interUltraLight, fontWeight: "ultralight" },
    { src: interUltraLight, fontWeight: "ultralight", fontStyle: "italic" },
    { src: interLight, fontWeight: "light" },
    { src: interLight, fontWeight: "light", fontStyle: "italic" },
    { src: interRegular, fontWeight: "normal" },
    { src: interRegular, fontWeight: "normal", fontStyle: "italic" },
    { src: interMedium, fontWeight: "medium" },
    { src: interMedium, fontWeight: "medium", fontStyle: "italic" },
    { src: interSemibold, fontWeight: "semibold" },
    { src: interSemibold, fontWeight: "semibold", fontStyle: "italic" },
    { src: interBold, fontWeight: "bold" },
    { src: interBold, fontWeight: "bold", fontStyle: "italic" },
    { src: interUltraBold, fontWeight: "ultrabold" },
    { src: interUltraBold, fontWeight: "ultrabold", fontStyle: "italic" },
    { src: interHeavy, fontWeight: "heavy" },
    { src: interHeavy, fontWeight: "heavy", fontStyle: "italic" },
  ],
});
