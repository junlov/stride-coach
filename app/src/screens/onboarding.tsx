import { PairConnection } from "../components/pair-connection";
import React, { useEffect, useState } from "react";
import { useRootNavigationState, useRouter } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { HistoryImport } from "../components/history-import";
import { GarminSettings } from "../components/garmin-settings";
import { ServerConnection } from "../components/server-connection";
import { Button, Card, Copy, Heading, Muted, Page } from "../components/ui";
import { useConnection } from "../state/connection";
import { useTheme } from "../theme";
import GoalScreen from "./goal";

// The import step can be replaced by hosts embedding this wizard.
export type ImportPastRunsStep = (props: {
  onContinue: () => void;
}) => React.ReactNode;

export function OnboardingScreen({
  importPastRunsStep: ImportPastRuns = GarminHistoryStep,
  onComplete,
  initialHasPlan,
}: {
  importPastRunsStep?: ImportPastRunsStep;
  onComplete?: () => void;
  initialHasPlan?: boolean;
}) {
  const { client, connectionVersion, finishOnboarding } = useConnection();
  const complete = onComplete ?? finishOnboarding;
  const [step, setStep] = useState<
    "server" | "garmin" | "import" | "goal" | "existing"
  >(initialHasPlan === undefined ? "server" : "garmin");
  const [hasPlan, setHasPlan] = useState(initialHasPlan ?? false);
  const [garminBusy, setGarminBusy] = useState(false);
  function goalStep() {
    setStep(hasPlan ? "existing" : "goal");
  }
  function afterGarmin() {
    setStep("import");
  }
  if (step === "goal") return <GoalScreen onComplete={complete} />;
  if (step === "import") return <ImportPastRuns onContinue={goalStep} />;
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
          ? "Welcome to Stride Coach · 1 of 4"
          : "Connect Garmin · 2 of 4"
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
            label="Continue to import"
            onPress={afterGarmin}
            disabled={garminBusy}
          />
          <Button
            label="Skip Garmin for now"
            variant="secondary"
            onPress={goalStep}
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

function GarminHistoryStep({ onContinue }: { onContinue: () => void }) {
  const [imported, setImported] = useState(false);
  return (
    <Page
      eyebrow="Import past runs · 3 of 4"
      title="Start with your running history."
    >
      <HistoryImport onComplete={() => setImported(true)} />
      <Button
        label="Continue to goal"
        onPress={onContinue}
        disabled={!imported}
      />
      <Button
        label="Skip import for now"
        variant="secondary"
        onPress={onContinue}
      />
      <Muted>
        Wait for Complete to use these runs in your initial fitness estimate.
      </Muted>
    </Page>
  );
}

export function FirstRunGate({ children }: React.PropsWithChildren) {
  const {
    connection,
    loading,
    onboarding,
    finishOnboarding,
    pairingLink,
    dismissPairing,
  } = useConnection();
  const [pairedPlan, setPairedPlan] = useState<boolean | undefined>(undefined);
  const [returnToToday, setReturnToToday] = useState(false);
  const { colors: c, dark } = useTheme();
  if (loading)
    return (
      <ActivityIndicator
        accessibilityLabel="Loading settings"
        color={c.accent}
      />
    );
  if (pairingLink)
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <Page eyebrow="Server connection" title="Connect your coach.">
          <PairConnection
            link={pairingLink}
            onCancel={dismissPairing}
            onSaved={(hasPlan) => {
              setPairedPlan(hasPlan);
              dismissPairing();
            }}
          />
        </Page>
      </SafeAreaView>
    );
  if (onboarding)
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.background }}>
        <StatusBar style={dark ? "light" : "dark"} />
        <OnboardingScreen
          initialHasPlan={connection ? pairedPlan : undefined}
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
