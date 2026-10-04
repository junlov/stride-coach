import { useCallback, useEffect, useRef, useState } from "react";
import { Linking, Modal, View } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useFocusEffect } from "expo-router";
import { ApiError, Connection, createClient } from "../api/client";
import {
  exchangePairing,
  normalizePairing,
  parsePairingLink,
} from "../api/pairing";
import { useTheme } from "../theme";
import { useConnection } from "../state/connection";
import { Button, Card, Copy, ErrorMessage, Field, Heading, Muted } from "./ui";

type Props = {
  link?: string;
  onSaved?: (hasPlan: boolean, connection: Connection) => void;
  onBusyChange?: (busy: boolean) => void;
  disabled?: boolean;
  onCancel?: () => void;
};

export function PairConnection(props: Props) {
  return <PairForm key={props.link ?? "scan"} {...props} />;
}

function initialPairing(link?: string) {
  if (!link) return { serverUrl: "", code: "", error: null };
  try {
    return { ...parsePairingLink(link), error: null };
  } catch (e) {
    return { serverUrl: "", code: "", error: (e as ApiError).message };
  }
}

function PairForm({
  link,
  onSaved,
  onCancel,
  onBusyChange,
  disabled = false,
}: Props) {
  const [initial] = useState(() => initialPairing(link));
  const { save, loading } = useConnection();
  const [server, setServer] = useState(initial.serverUrl);
  const [code, setCode] = useState(initial.code);
  const [scanning, setScanning] = useState(false);
  const [showCode, setShowCode] = useState(Boolean(link));
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(initial.error);
  const lock = useRef(false);
  // Retain an exchanged token only in memory so a failed secure save can be retried.
  const received = useRef<Connection | null>(null);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      received.current = null;
    };
  }, []);
  const readLink = useCallback((value: string) => {
    received.current = null;
    setSaved(false);
    setError(null);
    setScanning(false);
    try {
      const parsed = parsePairingLink(value);
      setServer(parsed.serverUrl);
      setCode(parsed.code);
      setShowCode(true);
    } catch (e) {
      setCode("");
      setError((e as ApiError).message);
    }
  }, []);
  useFocusEffect(useCallback(() => () => setScanning(false), []));

  function edit(set: (value: string) => void, value: string) {
    received.current = null;
    setSaved(false);
    setError(null);
    set(value);
  }
  async function connect() {
    if (lock.current || disabled) return;
    lock.current = true;
    setBusy(true);
    onBusyChange?.(true);
    setError(null);
    try {
      const connection =
        received.current ??
        (await exchangePairing(normalizePairing(server, code)));
      if (!active.current) return;
      received.current = connection;
      let hasPlan = true;
      try {
        await createClient(connection).status();
      } catch (e) {
        if (
          e instanceof ApiError &&
          e.status === 400 &&
          /^No plan\./i.test(e.message)
        )
          hasPlan = false;
        else throw e;
      }
      if (!active.current) return;
      await save(connection);
      if (!active.current) return;
      received.current = null;
      setCode("");
      setSaved(true);
      onSaved?.(hasPlan, connection);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not save secure settings. Try Connect to server again.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
      onBusyChange?.(false);
    }
  }
  return (
    <Card>
      <Heading>Connect from your computer</Heading>
      <Muted>
        Generate a pairing QR code on your computer, then scan it here. Codes
        expire in 10 minutes and work once.
      </Muted>
      <Button
        label="Scan to connect"
        disabled={busy || loading || disabled}
        onPress={() => {
          setError(null);
          setScanning(true);
        }}
      />
      <Button
        label="Enter pairing code"
        variant="secondary"
        disabled={busy || loading || disabled}
        onPress={() => setShowCode(true)}
      />
      {showCode && (
        <>
          <Field
            label="Pairing server URL"
            value={server}
            onChangeText={(v) => edit(setServer, v)}
            editable={!busy && !disabled}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder="https://coach.example.com"
          />
          <Field
            label="Pairing code"
            value={code}
            onChangeText={(v) => edit(setCode, v)}
            editable={!busy && !disabled}
            autoCapitalize="characters"
            autoCorrect={false}
            secureTextEntry
          />
          <Copy>
            Connect only if this is your server. Connecting replaces this
            phone’s saved connection.
          </Copy>
          <Button
            label={busy ? "Connecting..." : "Connect to server"}
            disabled={busy || loading || disabled || !code}
            onPress={() => void connect()}
          />
        </>
      )}
      <ErrorMessage message={error} />
      {saved && <Copy>Connection saved securely.</Copy>}
      {onCancel && (
        <Button
          label="Cancel pairing"
          variant="secondary"
          disabled={busy}
          onPress={onCancel}
        />
      )}
      <Modal
        visible={scanning}
        onRequestClose={() => setScanning(false)}
        animationType="slide"
      >
        {scanning && (
          <Scanner onScan={readLink} onClose={() => setScanning(false)} />
        )}
      </Modal>
    </Card>
  );
}

function Scanner({
  onScan,
  onClose,
}: {
  onScan: (link: string) => void;
  onClose: () => void;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const { colors } = useTheme();
  const [error, setError] = useState<string | null>(null);
  const scanned = useRef(false);
  return (
    <View
      style={{
        flex: 1,
        padding: 24,
        paddingTop: 64,
        backgroundColor: colors.background,
      }}
    >
      {permission?.granted ? (
        <CameraView
          style={{ flex: 1 }}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onMountError={() =>
            setError(
              "Camera unavailable. Enter the pairing code or use manual connection instead.",
            )
          }
          onBarcodeScanned={({ data }) => {
            if (!scanned.current) {
              scanned.current = true;
              onScan(data);
            }
          }}
        />
      ) : (
        <>
          <Copy>
            Allow camera access to scan your computer’s pairing QR code. You can
            also enter the code or connect manually.
          </Copy>
          <Button
            label="Allow camera"
            disabled={!permission || !permission.canAskAgain}
            onPress={() => {
              void requestPermission().catch(() =>
                setError("Could not request camera access."),
              );
            }}
          />
          {permission && !permission.canAskAgain && (
            <Button
              label="Open phone settings"
              onPress={() => {
                void Linking.openSettings().catch(() =>
                  setError("Open camera permissions in your phone settings."),
                );
              }}
            />
          )}
        </>
      )}
      <ErrorMessage message={error} />
      <Button label="Close scanner" variant="secondary" onPress={onClose} />
    </View>
  );
}
