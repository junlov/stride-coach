import React from "react";
import {
  Pressable,
  ScrollView,
  Text,
  TextInput,
  TextInputProps,
  View,
} from "react-native";
import { tokens, useTheme } from "../setup-theme";

export function Page({
  title,
  eyebrow,
  children,
}: React.PropsWithChildren<{ title: string; eyebrow?: string }>) {
  const c = useTheme();
  return (
    <ScrollView
      style={{ backgroundColor: c.background }}
      contentInsetAdjustmentBehavior="automatic"
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{
        flexGrow: 1,
        padding: tokens.space,
        gap: tokens.gap,
      }}
    >
      <Text
        style={{
          color: c.text,
          fontSize: 20,
          fontWeight: "600",
          letterSpacing: -0.4,
        }}
      >
        stride coach
      </Text>
      <View style={{ gap: 8, marginVertical: 8 }}>
        {eyebrow && (
          <Text
            style={{
              color: c.muted,
              fontSize: 12,
              letterSpacing: 1,
              textTransform: "uppercase",
            }}
          >
            {eyebrow}
          </Text>
        )}
        <Text
          accessibilityRole="header"
          style={{
            color: c.text,
            fontSize: 32,
            lineHeight: 37,
            letterSpacing: -0.6,
            fontWeight: "600",
          }}
        >
          {title}
        </Text>
      </View>
      {children}
    </ScrollView>
  );
}
export function Card({ children }: React.PropsWithChildren) {
  const c = useTheme();
  return (
    <View
      style={{
        borderTopWidth: 1,
        borderColor: c.border,
        paddingVertical: tokens.space,
        gap: tokens.gap,
      }}
    >
      {children}
    </View>
  );
}
export function Heading({ children }: React.PropsWithChildren) {
  const c = useTheme();
  return (
    <Text
      accessibilityRole="header"
      style={{ color: c.text, fontSize: 20, fontWeight: "600" }}
    >
      {children}
    </Text>
  );
}
export function Copy({ children }: React.PropsWithChildren) {
  const c = useTheme();
  return (
    <Text style={{ color: c.text, fontSize: 16, lineHeight: 24 }}>
      {children}
    </Text>
  );
}
export function Muted({ children }: React.PropsWithChildren) {
  const c = useTheme();
  return (
    <Text style={{ color: c.muted, fontSize: 14, lineHeight: 21 }}>
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
  const c = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{
        disabled,
        ...(selected === undefined ? {} : { selected }),
      }}
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => ({
        minHeight: tokens.touch,
        padding: 12,
        borderRadius: tokens.radius,
        alignItems: "center",
        justifyContent: "center",
        borderWidth: 1,
        borderColor:
          variant === "danger"
            ? c.error
            : variant === "primary"
              ? c.accent
              : c.border,
        backgroundColor: variant === "primary" ? c.accent : "transparent",
        opacity: disabled ? 0.45 : pressed ? 0.7 : 1,
      })}
    >
      <Text
        style={{
          color:
            variant === "primary"
              ? c.accentInk
              : variant === "danger"
                ? c.error
                : c.text,
          fontSize: 16,
          fontWeight: "600",
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}
export function Field({ label, ...props }: TextInputProps & { label: string }) {
  const c = useTheme();
  return (
    <View style={{ gap: 7 }}>
      <Muted>{label}</Muted>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={c.muted}
        style={{
          color: c.text,
          backgroundColor: c.card,
          borderColor: c.border,
          borderWidth: 1,
          borderRadius: tokens.radius,
          padding: 12,
          minHeight: tokens.touch,
          fontSize: 16,
        }}
        {...props}
      />
    </View>
  );
}
export function ErrorMessage({ message }: { message: string | null }) {
  const c = useTheme();
  return message ? (
    <Text
      accessibilityRole="alert"
      style={{ color: c.error, fontSize: 16, lineHeight: 24 }}
    >
      {message}
    </Text>
  ) : null;
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
