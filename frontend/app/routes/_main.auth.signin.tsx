import { CheckCircle, Loader2, Mail } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Button } from "~/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "~/components/ui/card";
import { Input } from "~/components/ui/input";
import { Label } from "~/components/ui/label";
import { useAuth } from "~/contexts/auth";

export function meta() {
  return [{ title: "Sign In - GameGame" }];
}

export default function SignInPage() {
  const navigate = useNavigate();
  const { login, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [magicLink, setMagicLink] = useState<string | null>(null);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate("/", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const result = await login(email);
      if (result.success) {
        setSubmitted(true);
        // In development, show the magic link for testing
        if (result.magicLink) {
          setMagicLink(result.magicLink);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send magic link");
    } finally {
      setIsLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="container mx-auto flex min-h-[60vh] items-center justify-center px-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
              <CheckCircle className="h-8 w-8 text-green-600" />
            </div>
            <CardTitle>Check your email</CardTitle>
            <CardDescription>
              We sent a magic link to <strong>{email}</strong>
            </CardDescription>
          </CardHeader>
          <CardContent className="text-center">
            <p className="text-sm text-muted-foreground mb-4">
              Click the link in your email to sign in. The link will expire in 15 minutes.
            </p>
            {/* Only show magic link in development mode - server only sends it in dev */}
            {(import.meta as { env?: { DEV?: boolean } }).env?.DEV && magicLink && (
              <div className="mt-4 p-4 bg-muted rounded-lg">
                <p className="text-xs text-muted-foreground mb-2">Development mode - Magic link:</p>
                <a href={magicLink} className="text-sm text-blue-600 hover:underline break-all">
                  {magicLink}
                </a>
              </div>
            )}
            <Button
              variant="ghost"
              className="mt-4"
              onClick={() => {
                setSubmitted(false);
                setMagicLink(null);
              }}
            >
              Use a different email
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto flex min-h-[60vh] items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Sign In</CardTitle>
          <CardDescription>Enter your email to receive a magic link</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  disabled={isLoading}
                  className="pl-9"
                />
              </div>
            </div>

            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Sending...
                </>
              ) : (
                "Send Magic Link"
              )}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            We'll send you a magic link to sign in. No password required!
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
