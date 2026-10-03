"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/page-header";

const GUIDES = [
  { id: "install", title: "Install MusicSeed", description: "Start the app on macOS or Linux." },
  { id: "connect", title: "Connect to Plex", description: "Sign in with Plex and pick your music library." },
  { id: "local-plex", title: "Plex on this computer", description: "Use your local Plex database." },
  { id: "remote-plex", title: "Plex on a server or NAS", description: "Fetch database snapshots over SSH." },
  { id: "copied-database", title: "Use a database copy", description: "Import a backup without SSH access." },
  { id: "first-playlist", title: "Import and make a playlist", description: "Turn your library into recommendations." },
];

function Guide({ id, number, title, children }: {
  id: string;
  number: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="panel quick-start-guide" aria-labelledby={`${id}-title`}>
      <header className="flex items-baseline gap-3">
        <span className="quick-start-number" aria-hidden="true">{number}</span>
        <h2 id={`${id}-title`} className="m-0 text-xl font-semibold">{title}</h2>
      </header>
      {children}
      <a href="#guides" className="quick-start-back">Back to guides ↑</a>
    </section>
  );
}

function Step({ title, children }: { title: string; children: ReactNode }) {
  return <li><h3>{title}</h3>{children}</li>;
}

function Command({ children, label = "Terminal command" }: { children: string; label?: string }) {
  return <pre tabIndex={0} aria-label={label}><code>{children}</code></pre>;
}

// Keep these instructions aligned with scripts/install.sh, the setup wizard,
// and docs/infra/local-runtime.md. This page must work without discovery or a database.
export default function QuickStartPage() {
  return (
    <>
      <PageHeader
        eyebrow="Getting started"
        title="Quick Start"
        description="From your first install to your first playlist. Follow the basics, then choose the guide that matches where Plex runs."
      />

      <section className="panel quick-start-welcome">
        <div>
          <h2 className="m-0 text-lg font-semibold">Your music stays in Plex</h2>
          <p className="mb-0 text-sm muted">
            MusicSeed reads your library into its own local database and recommends tracks
            from the music you already own. Start with installation and connection, choose
            one database guide, then import your library.
          </p>
        </div>
        <Link href="/setup" className="btn btn-primary shrink-0">Open setup wizard</Link>
      </section>

      <nav id="guides" aria-label="Quick Start guides" className="quick-start-index">
        {GUIDES.map((guide, index) => (
          <a key={guide.id} href={`#${guide.id}`} className="quick-start-card">
            <span className="quick-start-number" aria-hidden="true">0{index + 1}</span>
            <span>
              <strong className="block">{guide.title}</strong>
              <span className="block text-sm muted mt-1">{guide.description}</span>
            </span>
          </a>
        ))}
      </nav>

      <Guide id="install" number="01" title="Install MusicSeed">
        <p>Run these steps on the computer where you want MusicSeed to run. Plex can live on a different machine.</p>
        <ol className="quick-start-steps">
          <Step title="Check the prerequisites">
            <p>You need macOS or Linux, Python 3.12 or newer with venv support, Node.js with npm, and Git for the source download below. You also need a Plex music library.</p>
            <Command>{"python3 --version\nnode --version\nnpm --version\ngit --version"}</Command>
            <p className="muted">Node.js is used to build the website during installation. Starting MusicSeed afterward only needs Python.</p>
          </Step>
          <Step title="Download and install">
            <Command>{"git clone https://github.com/dafevara/musicseed.git musicseed\ncd musicseed\n./scripts/install.sh"}</Command>
            <p>Already have the source or an unpacked release? Open its directory and run <code>./scripts/install.sh</code>. The installer creates a Python environment, installs the app, and builds the web UI. Installation needs internet access.</p>
          </Step>
          <Step title="Start the app">
            <Command>{"musicseed --open"}</Command>
            <p>Keep the terminal running. The app opens at <code>http://127.0.0.1:8789</code> on this computer. If your browser does not open, enter that address yourself.</p>
            <details>
              <summary>Command not found, missing venv, or port already in use?</summary>
              <p>If <code>musicseed</code> is not on your PATH, run <code>./.venv/bin/musicseed --open</code> from the source directory.</p>
              <p>On Debian or Ubuntu, a missing venv error may require <code>sudo apt install python3-venv python3-pip</code>; then rerun the installer with Python 3.12 or newer.</p>
              <p>If port 8789 is occupied, use <code>musicseed --port 8790 --open</code>.</p>
            </details>
          </Step>
        </ol>
        <p className="quick-start-next">Next: <a href="#connect">connect to Plex</a>.</p>
      </Guide>

      <Guide id="connect" number="02" title="Connect to Plex">
        <p>The Plex connection lets MusicSeed save playlists. Database access, configured in the next guide, lets it import your library.</p>
        <ol className="quick-start-steps">
          <Step title="Choose your server">
            <p>Open the <Link href="/setup">setup wizard</Link> and select your Plex server. If discovery does not find it, enter its address in <strong>Plex server URL</strong>, for example <code>http://nas.local:32400</code>.</p>
            <p>For Plex on another computer, use that computer&apos;s reachable hostname or IP address. <code>127.0.0.1</code> refers to the computer running MusicSeed.</p>
          </Step>
          <Step title="Sign in with Plex">
            <p>Choose <strong>Sign in with Plex</strong> and finish signing in on the Plex page that opens. MusicSeed stores the returned token on this computer — there is no token to copy.</p>
            <p>No browser on this machine (a NAS or a server you reach over SSH)? Run <code>musicseed-cli plex-login</code> and enter the short code it prints at <code>plex.tv/link</code>. MusicSeed never displays the saved token.</p>
          </Step>
          <Step title="Confirm your music library">
            <p>Enter the exact name shown in Plex under <strong>Music library name</strong>, then choose <strong>Save &amp; re-check</strong>. A successful connection takes you to <strong>Review &amp; initialize</strong>.</p>
            <p>If a readable database is already available, <strong>Continue without Plex connection</strong> lets you import and recommend locally. You can add the Plex connection in <Link href="/settings">Settings</Link> before saving playlists.</p>
          </Step>
        </ol>
        <p className="quick-start-next">Next: choose <a href="#local-plex">local Plex</a>, <a href="#remote-plex">a remote server</a>, or <a href="#copied-database">a database copy</a>.</p>
      </Guide>

      <Guide id="local-plex" number="03" title="Plex on this computer">
        <p>Use this guide when Plex and MusicSeed run on the same computer.</p>
        <ol className="quick-start-steps">
          <Step title="Review the detected database">
            <p>In the wizard&apos;s <strong>Review &amp; initialize</strong> step, check that <strong>Plex library database</strong> is found. MusicSeed checks common macOS and Linux Plex locations automatically.</p>
          </Step>
          <Step title="Supply a path if it was not found">
            <p>In <strong>Finish your setup</strong>, leave <strong>Plex is on another machine (fetch the database over SSH)</strong> unchecked. Set <strong>Plex database path</strong> to the full path of <code>com.plexapp.plugins.library.db</code> in Plex&apos;s <code>Plug-in Support/Databases</code> folder. The user running MusicSeed must be able to read it.</p>
            <p>On macOS, start in <code>~/Library/Application Support/Plex Media Server/</code>. On Linux, check your Plex installation&apos;s data directory.</p>
          </Step>
          <Step title="Save and check the results">
            <p>Choose <strong>Save &amp; re-check</strong>. For sonic similarity, the companion <code>com.plexapp.plugins.library.blobs.db</code> should be beside the library database. You can import metadata even if the blobs file is missing.</p>
          </Step>
        </ol>
        <p className="quick-start-next">Next: <a href="#first-playlist">import your library</a>.</p>
      </Guide>

      <Guide id="remote-plex" number="04" title="Plex on a server or NAS">
        <p>MusicSeed can fetch consistent database snapshots over SSH while Plex keeps running. You do not need to copy your music files.</p>
        <ol className="quick-start-steps">
          <Step title="Prepare the Plex host">
            <p>Enable SSH on the server or NAS. Your SSH user needs permission to read Plex&apos;s databases and run commands. The remote host needs <code>python3</code> with its <code>sqlite3</code> module and enough temporary disk space for backups of both databases. Allow space on the MusicSeed computer for the downloaded snapshots too.</p>
            <p>Find the directory containing <code>com.plexapp.plugins.library.db</code> and, when available, <code>com.plexapp.plugins.library.blobs.db</code>. For Plex in a container, use the path visible to your SSH session on the host.</p>
          </Step>
          <Step title="Verify SSH access from the MusicSeed computer">
            <p>Replace the example user, host, and port below. Run this as the same local OS user who runs MusicSeed. Verify the server fingerprint through a trusted channel before accepting it; this records the host in <code>~/.ssh/known_hosts</code>.</p>
            <Command>{"ssh -p 22 your-user@nas.local"}</Command>
            <p>In that remote session, check Python&apos;s SQLite support, then return to your computer:</p>
            <Command label="Commands to run on the remote Plex host">{"python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'\nexit"}</Command>
          </Step>
          <Step title="Configure the remote database source">
            <p><a href="#connect">Connect to Plex</a> first. In <strong>Review &amp; initialize → Finish your setup</strong>, check <strong>Plex is on another machine (fetch the database over SSH)</strong>. Enter an <strong>SSH target</strong> using this format:</p>
            <Command label="Example SSH target field value">{"your-user@nas.local:/path/to/Plex Media Server/Plug-in Support/Databases"}</Command>
            <p>Point at the <strong>folder</strong> holding <code>com.plexapp.plugins.library.db</code>. Pasting the database file&apos;s own path works too, <code>~</code> is expanded on the remote host, and spaces need no escaping or quotes.</p>
            <p>Set <strong>SSH port</strong> if it is not 22. Use <strong>SSH password</strong> for password authentication. If no password is saved, MusicSeed uses standard SSH keys or your SSH agent. Leaving the password field blank keeps any previously saved password.</p>
          </Step>
          <Step title="Re-check, then import">
            <p>Choose <strong>Save &amp; re-check</strong>. Once the library database is found, continue to <a href="#first-playlist">initialize and import</a>. The import creates and downloads fresh SQLite snapshots, including committed changes from Plex&apos;s WAL files. Later imports refresh the snapshots.</p>
            <details>
              <summary>SSH works in my terminal, but the import fails?</summary>
              <p>MusicSeed connects without prompting, so a key that only lives in your terminal&apos;s agent is not enough: run <code>ssh-add</code> and make sure the process running MusicSeed can see <code>SSH_AUTH_SOCK</code> (a server started by <code>systemd</code> or <code>launchd</code> usually cannot), or enter an <strong>SSH password</strong>. MusicSeed does not read aliases from <code>~/.ssh/config</code>, so use the real hostname and user.</p>
              <p>Then check host trust for the user running MusicSeed, database read permissions, Python&apos;s SQLite support, and free space on both computers. Unknown or changed host keys must be verified before reconnecting.</p>
              <p>If a backup times out, retry when Plex is less busy. A failed transfer keeps the last published snapshot. Do not copy live WAL or SHM files into the cache to repair it.</p>
            </details>
          </Step>
        </ol>
        <p className="quick-start-next">No SSH command access or Python on the host? Use <a href="#copied-database">a database copy</a>.</p>
      </Guide>

      <Guide id="copied-database" number="05" title="Use a database copy">
        <p>Use this route when you already have consistent Plex database backups, or cannot use SSH snapshots.</p>
        <ol className="quick-start-steps">
          <Step title="Prepare a consistent backup">
            <p>Use a standalone SQLite backup of the library database and, if available, the blobs database. Avoid copying just the main database files while Plex is running: recent changes may still be in WAL files.</p>
            <p>For a manual file copy, shut down Plex cleanly first, copy the databases once it has stopped, then restart Plex. Keep the originals on the server.</p>
          </Step>
          <Step title="Place the files on the MusicSeed computer">
            <p>Keep <code>com.plexapp.plugins.library.db</code> and the optional <code>com.plexapp.plugins.library.blobs.db</code> together in a readable folder. A mounted folder containing consistent backups also works. Paths refer to the computer running MusicSeed, even if you open the UI from another device.</p>
          </Step>
          <Step title="Select the local copy in setup">
            <p>In <strong>Review &amp; initialize → Finish your setup</strong>, leave the SSH checkbox unchecked. Enter the full local library file path in <strong>Plex database path</strong> and choose <strong>Save &amp; re-check</strong>.</p>
            <p>This is your import source. Keep <strong>MusicSeed database path</strong> separate; its default is <code>~/.local/share/musicseed/musicseed.db</code>.</p>
          </Step>
          <Step title="Refresh the copy when your Plex library changes">
            <p>After any running import finishes, supply a new consistent backup and run import again. MusicSeed cannot fetch updates automatically from a manually copied database.</p>
          </Step>
        </ol>
        <p className="quick-start-next">Next: <a href="#first-playlist">import your library</a>.</p>
      </Guide>

      <Guide id="first-playlist" number="06" title="Import and make a playlist">
        <ol className="quick-start-steps">
          <Step title="Create MusicSeed’s local database">
            <p>Return to <Link href="/setup">Setup</Link>, review the source and destination, and choose <strong>Initialize database</strong> if it is shown. This creates MusicSeed&apos;s own database; Plex&apos;s source databases are only read.</p>
          </Step>
          <Step title="Import your library">
            <p>Choose <strong>Start import</strong> and keep MusicSeed running while the job completes. If an import stops early, use <strong>Resume import</strong>; completed batches are kept. Wait for active jobs to finish before changing settings.</p>
          </Step>
          <Step title="Add optional recommendation signals">
            <p>You can skip enrichment to start listening sooner. To add popularity data later, configure a ListenBrainz user token or Spotify credentials in <Link href="/settings">Settings</Link>, then start enrichment from <Link href="/">Library</Link>.</p>
            <p>For sonic similarity, Plex must already have analyzed your music. In <strong>Settings → Sonic vectors</strong>, choose <strong>Import from Plex</strong> to bring its existing analysis into MusicSeed.</p>
          </Step>
          <Step title="Preview your first playlist">
            <p>Open <Link href="/recommend">Recommend</Link>, choose seed tracks from your imported library, and review the suggestions. Use <Link href="/playlists">Playlists</Link> to preview a new playlist, then confirm the tracks before saving it to Plex. Saving requires a working Plex connection (sign in with Plex in the wizard or Settings).</p>
          </Step>
        </ol>
        <p className="quick-start-next">Ready to begin? <Link href="/setup">Open the setup wizard →</Link></p>
      </Guide>
    </>
  );
}
