import { AlertCircle } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";

const ERROR_MESSAGES: Record<string, string> = {
  invalid_token: "The sign-in link is invalid or has expired.",
  expired: "The sign-in link has expired. Please request a new one.",
  already_used: "This sign-in link has already been used.",
  unauthorized: "You are not authorized to access this resource.",
  default: "An error occurred during authentication.",
};

export function meta() {
  return [{ title: "Authentication Error - GameGame" }];
}

export default function AuthErrorPage() {
  const [searchParams] = useSearchParams();
  const errorCode = searchParams.get("error") || "default";
  const errorMessage =
    searchParams.get("message") || ERROR_MESSAGES[errorCode] || ERROR_MESSAGES.default;

  return (
    <div className="container mx-auto flex min-h-[60vh] items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-red-100">
            <AlertCircle className="h-8 w-8 text-red-600" />
          </div>
          <CardTitle>Authentication Error</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4 text-center">
          <p className="text-muted-foreground">{errorMessage}</p>
          <div className="flex gap-3">
            <Button asChild variant="outline">
              <Link to="/">Go Home</Link>
            </Button>
            <Button asChild>
              <Link to="/auth/signin">Sign In Again</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
