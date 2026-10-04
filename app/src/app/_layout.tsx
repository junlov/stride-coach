import { Tabs } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { Text } from "react-native";
import { ConnectionProvider } from "../state/connection";
import { useTheme } from "../theme";

function Navigation() {
  const { colors } = useTheme();
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
        name="week"
        options={{
          title: "Week",
          tabBarIcon: ({ color }) => <Text style={{ color }}>▦</Text>,
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
          href: null,
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
          href: null,
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
      <StatusBar style="auto" />
      <Navigation />
    </ConnectionProvider>
  );
}
