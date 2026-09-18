on run argv
    set crawlWindowId to (item 1 of argv) as integer
    set targetURL to item 2 of argv
    set loadTimeout to (item 3 of argv) as real
    tell application "Safari"
        set crawlTab to current tab of window id crawlWindowId
        set clearToken to "dblp-crawl-clear-" & (do shell script "/usr/bin/uuidgen")
        set URL of crawlTab to "data:text/html,%3Chtml%3E%3Cbody%3E" & clearToken & "%3C/body%3E%3C/html%3E"
        set clearedPage to false
        repeat 50 times
            if (source of crawlTab) contains clearToken then
                set clearedPage to true
                exit repeat
            end if
            delay 0.1
        end repeat
        if not clearedPage then error "Could not clear the previous page"
        set URL of crawlTab to targetURL
        set lastCapture to ""
        repeat (round (loadTimeout * 2) rounding up) times
            delay 0.5
            try
                set loadedURL to URL of crawlTab
                set pageHTML to source of crawlTab
                if loadedURL does not start with "data:" and pageHTML contains "</html>" and pageHTML does not contain clearToken then
                    set lastCapture to loadedURL & linefeed & pageHTML
                    -- Let Safari run the site's normal JavaScript challenge.
                    -- Python validates the final URL and classifies the response.
                    if pageHTML does not contain "anubis_challenge" then return lastCapture
                end if
            end try
        end repeat
        if lastCapture is not "" then return lastCapture
        error "Timed out waiting for complete HTML at " & targetURL
    end tell
end run
