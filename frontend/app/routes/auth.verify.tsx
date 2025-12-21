import { CheckCircle, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "~/components/ui/card";
import { Spinner } from "~/components/ui/spinner";
import { useAuth } from "~/contexts/auth";

export function meta() {
  return [{ title: "Verify - GameGame" }];
}

export default function VerifyPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { verify, isAuthenticated } = useAuth();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    // Only run on client
    if (typeof window === "undefined") return;

    // If already authenticated, redirect to home
    if (isAuthenticated) {
      navigate("/", { replace: true });
      return;
    }

    const token = searchParams.get("token");
    if (!token) {
      setStatus("error");
      setErrorMessage("No verification token provided");
      return;
    }

    const verifyToken = async () => {
      const success = await verify(token);
      if (success) {
        setStatus("success");
        // Redirect after a short delay
        setTimeout(() => {
          navigate("/", { replace: true });
        }, 1500);
      } else {
        setStatus("error");
        setErrorMessage("Invalid or expired verification link");
      }
    };

    verifyToken();
  }, [searchParams, verify, navigate, isAuthenticated]);

  return (
    <div className="container mx-auto flex min-h-[60vh] items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>
            {status === "loading" && "Verifying..."}
            {status === "success" && "Success!"}
            {status === "error" && "Verification Failed"}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4 text-center">
          {status === "loading" && (
            <>
              <Spinner size="lg" />
              <p className="text-muted-foreground">Verifying your sign-in link...</p>
            </>
          )}

          {status === "success" && (
            <>
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
                <CheckCircle className="h-8 w-8 text-green-600" />
              </div>
              <p className="text-muted-foreground">
                You have been signed in successfully. Redirecting...
              </p>
            </>
          )}

          {status === "error" && (
            <>
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-red-100">
                <XCircle className="h-8 w-8 text-red-600" />
              </div>
              <p className="text-muted-foreground">{errorMessage}</p>
              <Button asChild variant="outline">
                <Link to="/auth/signin">Try Again</Link>
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
