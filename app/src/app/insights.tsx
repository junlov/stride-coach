import Screen from "../screens/insights";
import { useConnection } from "../state/connection";
export default function Route() {
  const { connectionVersion } = useConnection();
  return <Screen key={connectionVersion} />;
}
