import { Tabs } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { Text } from "react-native";
import { ConnectionProvider } from "../state/connection";
import { colors } from "../components/ui";

function Navigation() {
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        sceneStyle: { backgroundColor: colors.background },
        tabBarStyle: { backgroundColor: colors.card },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Today",
          tabBarIcon: ({ color }) => <Text style={{ color }}>●</Text>,
        }}
      />
      <Tabs.Screen
        name="plan"
        options={{
          title: "Plan",
          tabBarIcon: ({ color }) => <Text style={{ color }}>≡</Text>,
        }}
      />
      <Tabs.Screen
        name="goal"
        options={{
          title: "Goal",
          tabBarIcon: ({ color }) => <Text style={{ color }}>◎</Text>,
        }}
      />
      <Tabs.Screen
        name="insights"
        options={{
          title: "Progress",
          tabBarIcon: ({ color }) => <Text style={{ color }}>▥</Text>,
        }}
      />
      <Tabs.Screen
        name="actions"
        options={{
          title: "Actions",
          tabBarIcon: ({ color }) => <Text style={{ color }}>↻</Text>,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: "Settings",
          tabBarIcon: ({ color }) => <Text style={{ color }}>⚙</Text>,
        }}
      />
    </Tabs>
  );
}
export default function RootLayout() {
  return (
    <ConnectionProvider>
      <StatusBar style="light" />
      <Navigation />
    </ConnectionProvider>
  );
}
