import React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
} from "react-native";
import { Link } from "expo-router";
import {
  displayFont,
  palettes,
  radius,
  spacing,
  typography,
  useTheme,
} from "../theme";
import { useConnection } from "../state/connection";
import { EmptyPlan } from "./empty-plan";
// Legacy exports remain compatible with settings and goal screens.
export const colors = palettes.dark;
export const styles = StyleSheet.create({
  page: {
    flexGrow: 1,
    padding: 20,
    gap: 16,
    backgroundColor: colors.background,
  },
  title: { color: colors.text, fontSize: 30, fontWeight: "700" },
  heading: { color: colors.text, fontSize: 20, fontWeight: "600" },
  text: { color: colors.text, fontSize: 16, lineHeight: 24 },
  muted: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  card: {
    padding: 18,
    borderRadius: 16,
    gap: 10,
    backgroundColor: colors.card,
  },
  input: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.muted,
    borderRadius: 10,
    padding: 12,
    color: colors.text,
    fontSize: 16,
    minHeight: 48,
  },
  button: {
    backgroundColor: colors.accent,
    borderRadius: 10,
    padding: 14,
    minHeight: 48,
    alignItems: "center",
  },
  buttonText: { color: colors.background, fontSize: 16, fontWeight: "700" },
});
export function Page({
  title,
  children,
  eyebrow,
}: React.PropsWithChildren<{ title: string; eyebrow?: string }>) {
  const { colors } = useTheme();
  return (
    <ScrollView
      style={{ backgroundColor: colors.background }}
      contentInsetAdjustmentBehavior="automatic"
      contentContainerStyle={[
        styles.page,
        { backgroundColor: colors.background, gap: spacing.lg },
      ]}
      keyboardShouldPersistTaps="handled"
    >
      {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
      <Text
        accessibilityRole="header"
        style={[
          typography.title,
          { color: colors.text, fontFamily: displayFont },
        ]}
      >
        {title}
      </Text>
      {children}
    </ScrollView>
  );
}
export function Card({ children }: React.PropsWithChildren) {
  const { colors } = useTheme();
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: colors.card,
          borderColor: colors.border,
          borderWidth: 0.5,
          borderCurve: "continuous",
        },
      ]}
    >
      {children}
    </View>
  );
}
export function Heading({ children }: React.PropsWithChildren) {
  const { colors } = useTheme();
  return (
    <Text
      accessibilityRole="header"
      style={[
        typography.heading,
        { color: colors.text, fontFamily: displayFont },
      ]}
    >
      {children}
    </Text>
  );
}
export function Copy({ children }: React.PropsWithChildren) {
  const { colors } = useTheme();
  return (
    <Text selectable style={[typography.body, { color: colors.text }]}>
      {children}
    </Text>
  );
}
export function Muted({ children }: React.PropsWithChildren) {
  const { colors } = useTheme();
  return (
    <Text style={[typography.caption, { color: colors.muted }]}>
      {children}
    </Text>
  );
}
export function Button({
  label,
  onPress,
  disabled = false,
  variant = "primary",
  selected,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger";
  selected?: boolean;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{
        disabled,
        ...(selected === undefined ? {} : { selected }),
      }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor:
            variant === "secondary"
              ? "transparent"
              : variant === "danger"
                ? colors.error
                : colors.accent,
          borderColor: variant === "secondary" ? colors.border : "transparent",
          borderWidth: 1,
          opacity: disabled ? 0.45 : pressed ? 0.7 : 1,
        },
      ]}
    >
      <Text
        style={[
          styles.buttonText,
          { color: variant === "secondary" ? colors.text : colors.onAccent },
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}
export function Field({ label, ...props }: TextInputProps & { label: string }) {
  const { colors } = useTheme();
  return (
    <View style={{ gap: 6 }}>
      <Text style={[styles.text, { color: colors.text }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={colors.muted}
        style={[
          styles.input,
          {
            backgroundColor: colors.background,
            color: colors.text,
            borderColor: colors.border,
          },
        ]}
        {...props}
      />
    </View>
  );
}
export function ErrorMessage({ message }: { message: string | null }) {
  const { colors } = useTheme();
  return message ? (
    <Text
      accessibilityRole="alert"
      style={[styles.text, { color: colors.error }]}
    >
      {message}
    </Text>
  ) : null;
}
export function ConnectionGate({ children }: React.PropsWithChildren) {
  const { client, loading, error } = useConnection();
  const { colors } = useTheme();
  if (loading)
    return (
      <ActivityIndicator
        accessibilityLabel="Loading settings"
        color={colors.accent}
      />
    );
  if (!client)
    return (
      <Card>
        <Heading>Connect your coach</Heading>
        <Copy>Add your server URL and bearer token to get started.</Copy>
        <ErrorMessage message={error} />
        <Link href="/settings" style={[styles.text, { color: colors.accent }]}>
          Open Settings
        </Link>
      </Card>
    );
  return <>{children}</>;
}
export function QueryState({
  loading,
  error,
  retry,
}: {
  loading: boolean;
  error: string | null;
  retry: () => void;
}) {
  const { colors } = useTheme();
  const auth = !!error && /Authentication failed/i.test(error);
  const outage = !!error && /Cannot reach|too long|50[0234]/i.test(error);
  if (error && /^No plan\./i.test(error)) return <EmptyPlan />;
  return (
    <>
      {loading && (
        <ActivityIndicator accessibilityLabel="Loading" color={colors.accent} />
      )}
      {error && (
        <Card>
          <Heading>
            {auth
              ? "Your connection needs attention."
              : outage
                ? "Your server is out of reach."
                : "Unable to load this view"}
          </Heading>
          <ErrorMessage message={error} />
          <Muted>
            {auth
              ? "Your server token was rejected. Update it in Settings. Garmin sign-in will not fix this connection."
              : "No offline copy is stored. Reconnect to read your current plan."}
          </Muted>
          {auth && <NavLink href="/settings" label="Open Settings" />}
          {!auth && !outage && <NavLink href="/goal" label="Open Goal setup" />}
          <Button label="Retry" onPress={retry} />
        </Card>
      )}
    </>
  );
}

export function Eyebrow({ children }: React.PropsWithChildren) {
  const { colors } = useTheme();
  return (
    <Text
      style={[
        typography.eyebrow,
        { color: colors.muted, textTransform: "uppercase" },
      ]}
    >
      {children}
    </Text>
  );
}
export function Badge({ children }: React.PropsWithChildren) {
  const { colors } = useTheme();
  return (
    <Text
      style={[
        typography.eyebrow,
        {
          color: colors.accent,
          borderColor: colors.accent,
          borderWidth: 1,
          borderRadius: radius.sm,
          padding: spacing.sm,
          alignSelf: "flex-start",
          textTransform: "uppercase",
        },
      ]}
    >
      {children}
    </Text>
  );
}
export function Hero({
  value,
  unit,
}: {
  value: string | number;
  unit: string;
}) {
  const { colors } = useTheme();
  return (
    <Text
      style={[typography.hero, { color: colors.text, fontFamily: displayFont }]}
    >
      {value}
      <Text style={{ fontSize: 24, letterSpacing: 0 }}> {unit}</Text>
    </Text>
  );
}
export function Metrics({
  items,
}: {
  items: { value: string | number; label: string }[];
}) {
  const { colors } = useTheme();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.page }}>
      {items.map((item) => (
        <View key={item.label} style={{ flex: 1, minWidth: 100 }}>
          <Text
            style={[
              typography.metric,
              { color: colors.text, fontFamily: displayFont },
            ]}
          >
            {item.value}
          </Text>
          <Muted>{item.label}</Muted>
        </View>
      ))}
    </View>
  );
}
export function Notice({
  title,
  children,
}: React.PropsWithChildren<{ title: string }>) {
  const { colors } = useTheme();
  return (
    <View
      style={{
        padding: spacing.lg,
        gap: spacing.sm,
        borderRadius: radius.notice,
        borderCurve: "continuous",
        backgroundColor: colors.notice,
        borderWidth: 1,
        borderColor: colors.border,
      }}
    >
      <Heading>{title}</Heading>
      {children}
    </View>
  );
}
export function NavLink({
  href,
  label,
  primary = false,
}: {
  href: React.ComponentProps<typeof Link>["href"];
  primary?: boolean;
  label: string;
}) {
  const { colors } = useTheme();
  return (
    <Link
      href={href}
      accessibilityRole="link"
      style={[
        typography.body,
        {
          color: primary ? colors.onAccent : colors.accent,
          backgroundColor: primary ? colors.accent : "transparent",
          borderRadius: radius.control,
          textAlign: primary ? "center" : "left",
          fontWeight: primary ? "600" : "400",
          paddingHorizontal: primary ? spacing.md : 0,
          paddingVertical: spacing.md,
          minHeight: 48,
          textDecorationLine: primary ? "none" : "underline",
        },
      ]}
    >
      {label}
    </Link>
  );
}

export function Choice<T extends string>({
  label,
  value,
  options,
  names,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: readonly T[];
  names: Record<T, string>;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const [expanded, setExpanded] = React.useState(false);
  return (
    <View style={{ gap: 7 }}>
      <Muted>{label}</Muted>
      <Button
        label={`${label}: ${names[value]} ${expanded ? "▴" : "▾"}`}
        variant="secondary"
        disabled={disabled}
        onPress={() => setExpanded(!expanded)}
      />
      {expanded &&
        options.map((option) => (
          <Button
            key={option}
            label={names[option]}
            selected={option === value}
            variant={option === value ? "primary" : "secondary"}
            disabled={disabled}
            onPress={() => {
              onChange(option);
              setExpanded(false);
            }}
          />
        ))}
    </View>
  );
}
