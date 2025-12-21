import { ArrowRight } from "lucide-react";
import { Link } from "react-router";
import { Button } from "~/components/ui/button";

export function meta() {
  return [
    { title: "GameGame - Board Game Rules Assistant" },
    {
      name: "description",
      content:
        "AI-powered assistant for board game rules. Ask questions about any game and get instant answers with citations.",
    },
  ];
}

export default function HomePage() {
  return (
    <div className="container mx-auto px-4 py-16">
      <div className="max-w-2xl mx-auto text-center">
        <h1 className="text-4xl font-bold mb-4">Welcome to GameGame</h1>
        <p className="text-xl text-muted-foreground mb-8">
          Your AI-powered assistant for board game rules. Ask questions about any game and get
          instant answers with citations.
        </p>
        <Button asChild size="lg">
          <Link to="/games">
            Browse Games
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      </div>
    </div>
  );
}
