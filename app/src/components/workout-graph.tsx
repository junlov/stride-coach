import { View } from "react-native";
import type { Schema } from "../api/client";
import { useTheme, spacing, radius } from "../theme";
import { Muted } from "./ui";

export function WorkoutGraph({
  workout,
}: {
  workout: Schema<"WorkoutSummary">;
}) {
  const { colors } = useTheme();
  const steps = workout.steps.flatMap((block) => {
    if (!("steps" in block)) return [block];
    return Array.from({ length: block.repetitions }, (_, rep) =>
      block.steps.filter(
        (_, index) =>
          !(
            block.skip_last_rest &&
            rep === block.repetitions - 1 &&
            index === block.steps.length - 1
          ),
      ),
    ).flat();
  });
  return (
    <>
      <View
        accessible
        accessibilityRole="image"
        accessibilityLabel={`Workout sequence: ${steps.map((s) => s.label).join(", ")}. Width shows estimated time.`}
        style={{
          flexDirection: "row",
          alignItems: "flex-end",
          gap: 2,
          height: 48,
        }}
      >
        {steps.map((step, index) => (
          <View
            key={index}
            style={{
              flex: step.minutes,
              minWidth: 1,
              borderRadius: radius.sm,
              height: step.pace_min
                ? 44
                : step.hr_zone === 1 || /walk|recovery/i.test(step.label)
                  ? 16
                  : 28,
              backgroundColor: step.pace_min ? colors.accent : colors.border,
            }}
          />
        ))}
      </View>
      <Muted>Workout sequence · Width shows estimated time</Muted>
      <View style={{ height: spacing.xs }} />
    </>
  );
}
