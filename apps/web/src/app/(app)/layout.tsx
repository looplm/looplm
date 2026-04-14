import "@xyflow/react/dist/style.css";
import NavigationWrapper from "@/components/navigation-wrapper";
import AuthGuard from "@/components/auth-guard";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <NavigationWrapper>
        {children}
      </NavigationWrapper>
    </AuthGuard>
  );
}
