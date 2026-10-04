import type React from "react";
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(),
  setItemAsync: jest.fn(),
  deleteItemAsync: jest.fn(),
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: "device",
}));
jest.mock("expo-router", () => {
  const ReactModule = jest.requireActual<typeof React>("react");
  return {
    useFocusEffect: (effect: React.EffectCallback) =>
      ReactModule.useEffect(effect, [effect]),
    Link: jest.requireActual("react-native").Text,
  };
});
