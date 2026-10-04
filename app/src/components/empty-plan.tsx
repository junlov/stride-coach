import { Link } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { Card, Copy, Heading, Muted } from "./setup-ui";
import { tokens, useTheme } from "../setup-theme";

export function EmptyPlan() {
  const c = useTheme();
  return (
    <View
      style={{
        backgroundColor: c.background,
        padding: tokens.space,
        borderRadius: tokens.radius,
      }}
    >
      <Card>
        <Heading>Start with a destination.</Heading>
        <Copy>
          No active plan yet. Choose a goal and a schedule that fits your life.
        </Copy>
        <Muted>
          Your server derives your starting fitness from stored activity
          history. One active plan per database is supported.
        </Muted>
        <Link href="/goal" asChild>
          <Pressable
            accessibilityRole="link"
            style={{
              backgroundColor: c.accent,
              padding: 12,
              minHeight: tokens.touch,
              borderRadius: tokens.radius,
              justifyContent: "center",
              alignItems: "center",
            }}
          >
            <Text
              style={{ color: c.accentInk, fontSize: 16, fontWeight: "600" }}
            >
              Set a running goal
            </Text>
          </Pressable>
        </Link>
      </Card>
    </View>
  );
}
