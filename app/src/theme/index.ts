import { Platform, useColorScheme } from "react-native";

// Approved Open Design slate/green palette, converted to native sRGB colors.
export const palettes = {
  light: {
    background: "#f1f6f7",
    card: "#fafcfc",
    text: "#142126",
    muted: "#46585f",
    accent: "#205334",
    error: "#963c2f",
    border: "#b9c8cc",
    notice: "#e0ebee",
    onAccent: "#fafcfc",
  },
  dark: {
    background: "#101e27",
    card: "#1b2d38",
    text: "#f2f6f5",
    muted: "#b8c9ce",
    accent: "#a6edaa",
    error: "#ffb9ac",
    border: "#526570",
    notice: "#24343e",
    onAccent: "#101e27",
  },
};
export const spacing = { xs: 4, sm: 8, md: 12, lg: 18, page: 20, xl: 28 };
export const radius = { sm: 6, control: 10, notice: 12, card: 16 };
export const typography = {
  title: {
    fontSize: 32,
    lineHeight: 37,
    fontWeight: "600" as const,
    letterSpacing: -0.6,
  },
  heading: { fontSize: 18, lineHeight: 25, fontWeight: "600" as const },
  body: { fontSize: 16, lineHeight: 24 },
  caption: { fontSize: 13, lineHeight: 21 },
  eyebrow: {
    fontSize: 11,
    lineHeight: 17,
    fontWeight: "600" as const,
    letterSpacing: 1.1,
  },
  hero: {
    fontSize: 64,
    lineHeight: 72,
    fontWeight: "600" as const,
    letterSpacing: -2.5,
  },
  metric: {
    fontSize: 30,
    lineHeight: 38,
    fontWeight: "600" as const,
    letterSpacing: -0.7,
  },
};
export const displayFont = Platform.select({
  ios: "Avenir Next",
  default: undefined,
});
export function useTheme() {
  const dark = useColorScheme() === "dark";
  return { colors: palettes[dark ? "dark" : "light"], dark };
}
