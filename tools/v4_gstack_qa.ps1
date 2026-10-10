$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$browser = Join-Path $root '.agents/skills/gstack/browse/dist/browse.exe'
$output = Join-Path $root 'research/results/healthcheck_postrepair/v4_dashboard_qa'
$checks = @()
$capture = 'JSON.stringify({team:document.querySelector("#agent-status").textContent,overflow:document.documentElement.scrollWidth>innerWidth,privateContent:/(?<![A-Za-z0-9])[A-Za-z]:[\\/]|Traceback|sk-proj-|tvly-|OPENAI_API_KEY|KRONOS_LAN_ACCESS_CODE/.test(document.body.innerText),roles:[...document.querySelectorAll(".agent-card")].map(c=>({status:c.querySelector("[data-role=status]").textContent,interpretation:c.querySelector("[data-role=argument]").textContent,facts:c.querySelector("[data-role=evidence]").textContent})),pipeline:document.querySelector(".pipeline-stage[data-stage=agents]").textContent,chart:[...document.querySelectorAll("canvas")].some(c=>{const p=c.getContext("2d")?.getImageData(0,0,c.width,c.height).data;return p&&p.some((v,i)=>i%4===3&&v>0)})})'
foreach ($test in @('A','B')) {
    foreach ($viewport in @(@('desktop','1440x1000'),@('phone','390x844'),@('ipad','834x1112'))) {
        & $browser viewport $viewport[1] | Out-Null
        & $browser console --clear | Out-Null
        & $browser goto "http://127.0.0.1:18976/app/dashboard.html?offline_test=$test" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Native gstack navigation failed' }
        $initial = ((& $browser js $capture) -join "`n") | ConvertFrom-Json
        & $browser reload | Out-Null
        $reloaded = ((& $browser js $capture) -join "`n") | ConvertFrom-Json
        & $browser js 'document.querySelector("#agent-section").scrollIntoView();true' | Out-Null
        & $browser screenshot --viewport (Join-Path $output "native_${test}_$($viewport[0]).png") | Out-Null
        $console = ((& $browser console --errors) -join "`n")
        $pass = $console.Contains('(no console errors)')
        foreach ($state in @($initial,$reloaded)) {
            $pass = $pass -and (-not $state.overflow) -and (-not $state.privateContent) -and $state.chart -and ($state.roles.Count -eq 3) -and $state.pipeline.Contains('3/3')
            foreach ($role in $state.roles) {
                $pass = $pass -and ($role.status -eq 'Saved') -and $role.interpretation.StartsWith('Research context:') -and (-not [string]::IsNullOrWhiteSpace($role.facts))
            }
        }
        $checks += @{test=$test;viewport=$viewport[0];pass=$pass;initial=$initial;reloaded=$reloaded;console_errors= -not $console.Contains('(no console errors)')}
    }
}
$network = ((& $browser network) -join "`n")
$outside = $network -match 'https?://(?!127\.0\.0\.1:18976)'
$status = if (($checks | Where-Object { -not $_.pass }).Count -eq 0 -and -not $outside) { 'PASS' } else { 'FINDINGS' }
$report = @{status=$status;checks=$checks;external_calls=0;external_request_detected=$outside;native_browser_build=(Get-Content (Join-Path $root '.agents/skills/gstack/browse/dist/.version') -Raw).Trim();scope='Native gstack browser on read-only loopback synthetic server; desktop, phone, iPad, cached reload, fact/interpretation separation and console. No real providers or credentials.'}
$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $output 'native_gstack_qa.json') -Encoding UTF8
Write-Output "Native gstack QA: $status; cases: $($checks.Count); external request detected: $outside"
if ($status -ne 'PASS') { exit 1 }
