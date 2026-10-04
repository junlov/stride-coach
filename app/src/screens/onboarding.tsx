import React, { useEffect, useState } from "react";
import { useRootNavigationState, useRouter } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { GarminSettings } from "../components/garmin-settings";
import { ServerConnection } from "../components/server-connection";
import {
  Button,
  Card,
  Copy,
  Heading,
  Muted,
  Page,
} from "../components/setup-ui";
import { useConnection } from "../state/connection";
import { useTheme } from "../setup-theme";
import GoalScreen from "./goal";

// Extension slot: Import past runs. Hidden until a server-backed step is supplied.
export type ImportPastRunsStep = (props: {
  onContinue: () => void;
}) => React.ReactNode;

export function OnboardingScreen({
  importPastRunsStep: ImportPastRuns,
  onComplete,
}: {
  importPastRunsStep?: ImportPastRunsStep;
  onComplete?: () => void;
}) {
  const { client, connectionVersion, finishOnboarding } = useConnection();
  const complete = onComplete ?? finishOnboarding;
  const [step, setStep] = useState<
    "server" | "garmin" | "import" | "goal" | "existing"
  >("server");
  const [hasPlan, setHasPlan] = useState(false);
  const [garminBusy, setGarminBusy] = useState(false);
  function goalStep() {
    setStep(hasPlan ? "existing" : "goal");
  }
  function afterGarmin() {
    if (ImportPastRuns) setStep("import");
    else goalStep();
  }
  if (step === "goal") return <GoalScreen onComplete={complete} />;
  if (step === "import" && ImportPastRuns)
    return <ImportPastRuns onContinue={goalStep} />;
  if (step === "existing")
    return (
      <Page eyebrow="Your coach is connected" title="Your plan is ready.">
        <Card>
          <Heading>Keep your rhythm.</Heading>
          <Copy>
            This server already has a plan. You can start reading your week now.
          </Copy>
        </Card>
        <Button label="Go to Today" onPress={complete} />
      </Page>
    );
  return (
    <Page
      eyebrow={
        step === "server"
          ? "Welcome to Stride Coach · 1 of 3"
          : "Connect Garmin · 2 of 3"
      }
      title={
        step === "server"
          ? "Your running. Your server."
          : "Bring your runs together."
      }
    >
      {step === "server" ? (
        <>
          <Copy>
            Connect to your private coach. Your server stores your training
            history.
          </Copy>
          <ServerConnection
            onSaved={(exists) => {
              setHasPlan(exists);
              setStep("garmin");
            }}
          />
        </>
      ) : (
        <>
          {client && (
            <GarminSettings
              key={connectionVersion}
              client={client}
              onBusyChange={setGarminBusy}
              showHeading={false}
            />
          )}
          <Button
            label="Continue to goal"
            onPress={afterGarmin}
            disabled={garminBusy}
          />
          <Button
            label="Skip Garmin for now"
            variant="secondary"
            onPress={afterGarmin}
            disabled={garminBusy}
          />
          <Muted>
            You can connect later in Settings. Your plan uses the activities
            already stored on your server.
          </Muted>
        </>
      )}
      <Muted>PRIVATE TRAINING · YOUR SERVER</Muted>
    </Page>
  );
}

export function FirstRunGate({ children }: React.PropsWithChildren) {
  const { loading, onboarding, finishOnboarding } = useConnection();
  const [returnToToday, setReturnToToday] = useState(false);
  const c = useTheme();
  if (loading)
    return (
      <ActivityIndicator
        accessibilityLabel="Loading settings"
        color={c.accent}
      />
    );
  if (onboarding)
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <StatusBar style={c.background === "#101e27" ? "light" : "dark"} />
        <OnboardingScreen
          onComplete={() => {
            setReturnToToday(true);
            finishOnboarding();
          }}
        />
      </SafeAreaView>
    );
  return (
    <>
      {children}
      {returnToToday && <ReturnToToday onReturned={setReturnToToday} />}
    </>
  );
}

function ReturnToToday({
  onReturned,
}: {
  onReturned: (pending: boolean) => void;
}) {
  const navigation = useRootNavigationState();
  const router = useRouter();
  useEffect(() => {
    if (!navigation?.key) return;
    router.replace("/");
    onReturned(false);
  }, [navigation?.key, router, onReturned]);
  return null;
}
