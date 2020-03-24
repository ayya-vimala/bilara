import { html } from 'lit-element';

export const ColumnStyles = html`
<style>

[field] {
    flex-basis: 50%;
}

[field*="reference"] {
    flex-basis: 20%;
}

</style>
`