import { useColorScheme } from "react-native";

// Approved mobile review palette. Shared by onboarding and account settings.
export const palettes = {
  light: {
    background: "#f1f6f8",
    card: "#fafcfd",
    text: "#0f1f26",
    muted: "#44565d",
    border: "#748389",
    accent: "#154829",
    accentInk: "#fafcfd",
    error: "#8d251f",
  },
  dark: {
    background: "#101e27",
    card: "#1b2d38",
    text: "#f2f6f5",
    muted: "#b8c9ce",
    border: "#6c8490",
    accent: "#a6edaa",
    accentInk: "#101e27",
    error: "#ffb9ac",
  },
};
export const tokens = { space: 20, gap: 16, radius: 10, touch: 48 };
export function useTheme() {
  return palettes[useColorScheme() === "dark" ? "dark" : "light"];
}
