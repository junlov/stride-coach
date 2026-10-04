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
import { useConnection } from "../state/connection";
export const colors = {
  background: "#101e27",
  card: "#1b2d38",
  text: "#f2f6f5",
  muted: "#b8c9ce",
  accent: "#a6edaa",
  error: "#ffb9ac",
};
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
}: React.PropsWithChildren<{ title: string }>) {
  return (
    <ScrollView
      contentContainerStyle={styles.page}
      keyboardShouldPersistTaps="handled"
    >
      <Text accessibilityRole="header" style={styles.title}>
        {title}
      </Text>
      {children}
    </ScrollView>
  );
}
export function Card({ children }: React.PropsWithChildren) {
  return <View style={styles.card}>{children}</View>;
}
export function Heading({ children }: React.PropsWithChildren) {
  return (
    <Text accessibilityRole="header" style={styles.heading}>
      {children}
    </Text>
  );
}
export function Copy({ children }: React.PropsWithChildren) {
  return <Text style={styles.text}>{children}</Text>;
}
export function Muted({ children }: React.PropsWithChildren) {
  return <Text style={styles.muted}>{children}</Text>;
}
export function Button({
  label,
  onPress,
  disabled = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[styles.button, disabled && { opacity: 0.45 }]}
    >
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
}
export function Field({ label, ...props }: TextInputProps & { label: string }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.text}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={colors.muted}
        style={styles.input}
        {...props}
      />
    </View>
  );
}
export function ErrorMessage({ message }: { message: string | null }) {
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
        <Link href="/settings" style={styles.text}>
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
  return (
    <>
      {loading && (
        <ActivityIndicator accessibilityLabel="Loading" color={colors.accent} />
      )}
      {error && (
        <Card>
          <ErrorMessage message={error} />
          <Muted>If you have not created a plan yet, open Goal setup.</Muted>
          <Button label="Retry" onPress={retry} />
        </Card>
      )}
    </>
  );
}
