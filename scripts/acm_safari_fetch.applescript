on run argv
    set crawlWindowId to (item 1 of argv) as integer
    set targetURL to item 2 of argv
    set loadTimeout to (item 3 of argv) as real
    tell application "Safari"
        set crawlTab to current tab of window id crawlWindowId
        -- Observe a unique document in source, not just a changed URL. Safari
        -- can expose the new URL while still returning the previous HTML.
        set clearToken to "acm-crawl-clear-" & (do shell script "/usr/bin/uuidgen")
        set clearURL to "data:text/html,%3Chtml%3E%3Cbody%3E" & clearToken & "%3C/body%3E%3C/html%3E"
        set URL of crawlTab to clearURL
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
        repeat (round (loadTimeout * 2) rounding up) times
            delay 0.5
            set loadedURL to URL of crawlTab
            try
                set pageHTML to source of crawlTab
                if loadedURL is targetURL and pageHTML contains "</html>" and pageHTML does not contain clearToken then
                    return loadedURL & linefeed & pageHTML
                end if
            end try
        end repeat
        error "Timed out waiting for complete HTML at " & targetURL
    end tell
end run
