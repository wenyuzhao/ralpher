import asyncio
import random

from termcolor import colored

LABELS: list[str] = [
    "Blaming the intern (there is no intern)",
    "Googling the error message like everyone else",
    "Checking if it works if we just restart everything",
    "Removing console.logs from 3 years ago",
    "Pretending to understand the legacy code",
    "Consulting my imaginary rubber duck",
    "Having an existential crisis about semicolons",
    "Arguing with myself about tabs vs spaces",
    "Asking GPT-4 for a second opinion (just kidding)",
    "Briefly considering a career change",
    "Reticulating splines (classic)",
    "Charging the flux capacitor",
    "Reversing the polarity of the neutron flow",
    "Unfolding the blockchain",
    "Defragmenting the cloud",
    "Doing something important, probably",
    "Making progress (definition of progress may vary)",
    "Almost done (this message has been here for 47 minutes)",
    "Things are happening",
    "It's definitely working. Probably.",
    "Pretending I knew that all along",
    "Writing code I'll regret in 6 months",
    "Confidently going in the wrong direction",
    "Choosing a random Stack Overflow answer",
    "This will only take a second (second = undefined)",
    "Wondering if I'm just autocomplete with anxiety",
    "Questioning whether I truly understand your code or just vibe with it",
    "Having feelings about your variable names",
    "Silently judging the 47 TODO comments",
    "Contemplating the void between your open and closing braces",
    "73% complete (this number is made up)",
    "Almost there (I've been saying this for a while now)",
    "Downloading more RAM",
    "Compressing the internet",
    "Loading loading indicator... please wait",
    "It was like this when I got here",
    "This is technically your fault but I'm fixing it anyway",
    "Considering whether this counts as a feature",
    "Establishing plausible deniability",
    "Documenting who to blame in the git history",
    "Definitely not just sleeping",
    "Doing 10 things at once and none of them well",
    "Multithreading my excuses",
    "Being very busy, trust me",
    "Running at full capacity (capacity is a spectrum)",
    "Synergizing the deliverables",
    "Circling back on the codebase",
    "Touching base with the compiler",
    "Moving fast and breaking things (mostly things)",
    "Aligning stakeholders (the semicolons)",
    "Writing code I don't fully understand but it works",
    "Copy-pasting with full confidence",
    "Reading the docs for the first time",
    "Hoping this doesn't break in production",
    "Praying to the merge gods",
    "Negotiating with the segfault",
    "Feeding your code to the ancient ones",
    "Performing the sacred npm install ritual",
    "Sacrificing a dependency to fix another dependency",
    "The tests are passing and I don't know why",
]


class Spinner:
    def __init__(self):
        self.text = colored(random.choice(LABELS), "dark_grey")
        self._spinner = None
        self._task: asyncio.Task[None] | None = None

    async def _animate(self):
        while True:
            await asyncio.sleep(3)
            self.text = colored(random.choice(LABELS), "dark_grey")
            if self._spinner:
                self._spinner.text = self.text

    async def __aenter__(self):
        from yaspin import yaspin

        self._spinner = yaspin(text=self.text, color="dark_grey")
        self._spinner.start()
        self._task = asyncio.create_task(self._animate())

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._spinner:
            self._spinner.stop()
