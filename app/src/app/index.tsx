import Screen from "../screens/today";
import { useConnection } from "../state/connection";
export default function Route() {
  const { connectionVersion } = useConnection();
  return <Screen key={connectionVersion} />;
}
